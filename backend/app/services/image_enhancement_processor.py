"""Локальный процессор улучшения изображений (Pillow).

Безопасное автоулучшение БЕЗ AI: яркость/контраст, баланс белого, лёгкий
denoise/sharpen, ресайз и конвертация в рабочий формат. Работает в памяти
(bytes -> bytes) и НЕ изменяет оригинал.

Принципы безопасности:
- цвет и текстура изделия — критичны: коррекция цвета (баланс белого) и denoise
  ОГРАНИЧЕНЫ узкими коэффициентами и считаются «спорными» — на них процессор
  добавляет предупреждение, чтобы вышестоящий сервис отправил копию на review;
- никакой «точечной ретуши» (удаление пятен/грязи) локальными фильтрами не
  выполняется — это задача будущего AI-этапа (см. ``app/ai/image_editing.py``).

HEIC поддерживается через ``pillow-heif`` (если установлен). Если изображение
нельзя открыть, метод бросает понятную ``UnsupportedImageError`` (не падает).
"""

from dataclasses import dataclass, field
from io import BytesIO

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

try:  # HEIC/HEIF опционален: при отсутствии плагина .heic просто не откроется.
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIF_AVAILABLE = True
except Exception:  # отсутствие/поломка плагина не должны ронять импорт модуля
    _HEIF_AVAILABLE = False

# Предупреждение для спорных правок (цвет/текстура изделия).
PRODUCT_FIDELITY_WARNING = (
    "Автоулучшение не должно искажать реальный цвет/качество изделия — "
    "проверьте копию вручную перед публикацией"
)

# Операции, потенциально меняющие реальный цвет/текстуру товара (спорные).
DISPUTABLE_OPERATIONS = frozenset({"white_balance", "denoise"})

# Формат вывода -> формат Pillow.
_PIL_FORMATS = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "webp": "WEBP"}


class ImageEnhancementError(Exception):
    """Базовая ошибка улучшения изображения."""


class UnsupportedImageError(ImageEnhancementError):
    """Изображение нельзя открыть/обработать (битый файл, неизвестный формат, HEIC без плагина)."""


class ImageTooLargeError(ImageEnhancementError):
    """Изображение превышает допустимый размер (MEDIA_ENHANCEMENT_MAX_IMAGE_MB)."""


@dataclass(slots=True)
class _Profile:
    """Параметры профиля улучшения."""

    max_side: int
    auto_contrast: bool
    brightness: bool
    white_balance: bool
    denoise: bool
    sharpen: bool
    sharpen_percent: int = 90
    sharpen_radius: float = 1.2
    denoise_size: int = 3
    resize: bool = True
    convert: bool = True


# Профили обработки. Баланс белого/denoise — только в product_clean (спорные).
PROFILES: dict[str, _Profile] = {
    "social_safe": _Profile(
        max_side=2048,
        auto_contrast=True,
        brightness=True,
        white_balance=False,
        denoise=False,
        sharpen=True,
        sharpen_percent=80,
        sharpen_radius=1.2,
    ),
    "product_clean": _Profile(
        max_side=2048,
        auto_contrast=True,
        brightness=True,
        white_balance=True,
        denoise=True,
        sharpen=True,
        sharpen_percent=120,
        sharpen_radius=1.5,
        denoise_size=3,
    ),
    "minimal": _Profile(
        max_side=2048,
        auto_contrast=False,
        brightness=False,
        white_balance=False,
        denoise=False,
        sharpen=False,
    ),
}

DEFAULT_PROFILE = "social_safe"

_OPERATION_FLAGS = (
    "auto_contrast",
    "brightness",
    "white_balance",
    "denoise",
    "sharpen",
    "resize",
    "convert",
)


@dataclass(slots=True)
class EnhancedImageResult:
    """Результат улучшения изображения (в памяти)."""

    output_bytes: bytes
    output_format: str
    width: int
    height: int
    file_size: int
    operations_applied: list[str]
    before_metadata: dict[str, object]
    after_metadata: dict[str, object]
    quality_score: float
    warnings: list[str] = field(default_factory=list)


class ImageEnhancementProcessor:
    """Улучшает изображения локально через Pillow (без сети и AI)."""

    def __init__(
        self,
        output_format: str = "jpg",
        jpeg_quality: int = 92,
        max_image_mb: int = 25,
    ) -> None:
        fmt = output_format.strip().lower().lstrip(".")
        if fmt not in _PIL_FORMATS:
            fmt = "jpg"
        self._output_format = fmt
        self._jpeg_quality = max(1, min(100, jpeg_quality))
        self._max_bytes = max(1, max_image_mb) * 1024 * 1024

    @property
    def heif_available(self) -> bool:
        """Доступна ли поддержка HEIC/HEIF (установлен pillow-heif)."""
        return _HEIF_AVAILABLE

    def _resolve_profile(self, profile: str) -> _Profile:
        return PROFILES.get(profile, PROFILES[DEFAULT_PROFILE])

    def _effective_flags(
        self, base: _Profile, operations: dict[str, bool] | None
    ) -> dict[str, bool]:
        flags = {
            "auto_contrast": base.auto_contrast,
            "brightness": base.brightness,
            "white_balance": base.white_balance,
            "denoise": base.denoise,
            "sharpen": base.sharpen,
            "resize": base.resize,
            "convert": base.convert,
        }
        if operations:
            for key, value in operations.items():
                if key in _OPERATION_FLAGS:
                    flags[key] = bool(value)
        return flags

    def enhance_image_bytes(
        self,
        image_bytes: bytes,
        profile: str,
        operations: dict[str, bool] | None = None,
    ) -> EnhancedImageResult:
        """Улучшить изображение (bytes -> bytes). Оригинал не меняется."""
        if len(image_bytes) > self._max_bytes:
            raise ImageTooLargeError(
                f"Изображение {len(image_bytes)} байт превышает лимит "
                f"{self._max_bytes} байт ({self._max_bytes // (1024 * 1024)} МБ)"
            )

        prof = self._resolve_profile(profile)
        flags = self._effective_flags(prof, operations)

        try:
            with Image.open(BytesIO(image_bytes)) as opened:
                opened.load()
                before: dict[str, object] = {
                    "format": opened.format,
                    "mode": opened.mode,
                    "width": opened.width,
                    "height": opened.height,
                    "size_bytes": len(image_bytes),
                }
                work = opened.convert("RGB")
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            hint = "" if _HEIF_AVAILABLE else " (для HEIC нужен пакет pillow-heif)"
            raise UnsupportedImageError(f"Не удалось открыть изображение{hint}: {exc}") from exc

        applied: list[str] = []
        warnings: list[str] = []

        if flags["convert"]:
            applied.append("convert")

        if flags["resize"]:
            before_size = work.size
            work.thumbnail((prof.max_side, prof.max_side), Image.Resampling.LANCZOS)
            if work.size != before_size:
                applied.append("resize")

        if flags["auto_contrast"]:
            work = ImageOps.autocontrast(work, cutoff=1)
            applied.append("auto_contrast")

        if flags["white_balance"]:
            work = self._apply_white_balance(work)
            applied.append("white_balance")

        if flags["brightness"]:
            work = self._apply_brightness(work)
            applied.append("brightness")

        if flags["denoise"]:
            work = work.filter(ImageFilter.MedianFilter(size=prof.denoise_size))
            applied.append("denoise")

        if flags["sharpen"]:
            work = work.filter(
                ImageFilter.UnsharpMask(
                    radius=prof.sharpen_radius, percent=prof.sharpen_percent, threshold=2
                )
            )
            applied.append("sharpen")

        if any(op in DISPUTABLE_OPERATIONS for op in applied):
            warnings.append(PRODUCT_FIDELITY_WARNING)

        output_bytes = self._encode(work)
        quality = self._quality_score(work)
        after: dict[str, object] = {
            "format": self._output_format,
            "mode": work.mode,
            "width": work.width,
            "height": work.height,
            "size_bytes": len(output_bytes),
            "quality_score": quality,
        }

        return EnhancedImageResult(
            output_bytes=output_bytes,
            output_format=self._output_format,
            width=work.width,
            height=work.height,
            file_size=len(output_bytes),
            operations_applied=applied,
            before_metadata=before,
            after_metadata=after,
            quality_score=quality,
            warnings=warnings,
        )

    def build_output_file_name(
        self, media_asset_id: int, original_file_name: str, profile: str, output_format: str
    ) -> str:
        """Построить имя выходного файла копии (без перезаписи оригинала)."""
        has_ext = "." in original_file_name
        stem = original_file_name.rsplit(".", 1)[0] if has_ext else original_file_name
        stem = stem.replace("/", "_").replace("\\", "_").strip() or "image"
        ext = output_format.strip().lower().lstrip(".") or self._output_format
        return f"{media_asset_id}_{stem}_{profile}.{ext}"

    # --- Внутреннее ---

    @staticmethod
    def _apply_brightness(img: Image.Image) -> Image.Image:
        """Мягко скорректировать яркость к середине + лёгкая насыщенность."""
        gray_mean = ImageStat.Stat(img.convert("L")).mean[0] or 1.0
        factor = max(0.92, min(1.12, 128.0 / gray_mean))
        adjusted = ImageEnhance.Brightness(img).enhance(factor)
        return ImageEnhance.Color(adjusted).enhance(1.05)

    @staticmethod
    def _apply_white_balance(img: Image.Image) -> Image.Image:
        """Баланс белого (gray-world) с жёстким ограничением коэффициентов.

        Коэффициенты ограничены диапазоном [0.85, 1.15], чтобы не искажать
        реальный цвет ткани/изделия.
        """
        means = ImageStat.Stat(img).mean
        if len(means) < 3:
            return img
        gray = sum(means[:3]) / 3.0
        r, g, b = img.split()[:3]

        def scale(channel: Image.Image, mean: float) -> Image.Image:
            factor = 1.0 if mean <= 0 else max(0.85, min(1.15, gray / mean))
            return channel.point(lambda v, f=factor: int(min(255.0, max(0.0, v * f))))

        return Image.merge("RGB", (scale(r, means[0]), scale(g, means[1]), scale(b, means[2])))

    def _encode(self, img: Image.Image) -> bytes:
        pil_format = _PIL_FORMATS[self._output_format]
        buffer = BytesIO()
        if pil_format == "JPEG":
            img.save(buffer, format="JPEG", quality=self._jpeg_quality, optimize=True)
        elif pil_format == "PNG":
            img.save(buffer, format="PNG", optimize=True)
        else:
            img.save(buffer, format=pil_format, quality=self._jpeg_quality)
        return buffer.getvalue()

    @staticmethod
    def _quality_score(img: Image.Image) -> float:
        """Грубая эвристика качества [0..1] по контрасту и экспозиции."""
        grayscale = img.convert("L")
        stat = ImageStat.Stat(grayscale)
        mean = stat.mean[0]
        stddev = stat.stddev[0]
        contrast_score = min(stddev, 64.0) / 64.0
        exposure_score = 1.0 - abs(mean - 128.0) / 128.0
        score = 0.5 * contrast_score + 0.5 * exposure_score
        return round(max(0.0, min(1.0, score)), 4)

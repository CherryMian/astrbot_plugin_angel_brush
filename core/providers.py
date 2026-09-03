"""Provider payload builders."""

from __future__ import annotations

import base64
from typing import Any

# ---------- helpers ----------


def _trim_opt(v: Any) -> str | None:
    t = str(v).strip() if v is not None else ""
    return t if t else None


def effective_size(req: dict[str, Any], model: dict[str, Any]) -> str | None:
    return _trim_opt(req.get("size")) or _trim_opt(model.get("default_size"))


def effective_aspect(req: dict[str, Any], model: dict[str, Any]) -> str | None:
    return _trim_opt(req.get("aspect_ratio")) or _trim_opt(
        model.get("default_aspect_ratio")
    )


def effective_quality(req: dict[str, Any], model: dict[str, Any]) -> str | None:
    return _trim_opt(req.get("quality")) or _trim_opt(model.get("default_quality"))


def effective_prompt(req: dict[str, Any]) -> str:
    p = str(req.get("prompt") or "").strip()
    neg = _trim_opt(req.get("negative_prompt"))
    if neg:
        return f"{p}\n\n请避免出现以下内容：{neg}"
    return p


def parse_pixel_size(value: str) -> tuple[int, int] | None:
    s = value.strip().lower().replace("×", "x")
    if "x" not in s:
        return None
    w, h = s.split("x", 1)
    try:
        wi, hi = int(w.strip()), int(h.strip())
    except ValueError:
        return None
    if wi == 0 or hi == 0:
        return None
    return wi, hi


def _gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return max(1, a)


def aspect_from_dimensions(w: int, h: int) -> str:
    g = _gcd(w, h)
    return f"{w // g}:{h // g}"


def parse_aspect_ratio(value: str) -> tuple[int, int] | None:
    if ":" not in value:
        return None
    w, h = value.strip().split(":", 1)
    try:
        wi, hi = int(w.strip()), int(h.strip())
    except ValueError:
        return None
    if wi == 0 or hi == 0:
        return None
    return wi, hi


def openai_size_from_aspect(value: str, arbitrary: bool) -> str | None:
    parsed = parse_aspect_ratio(value)
    if not parsed:
        return None
    w, h = parsed
    ratio = w / h
    if arbitrary:
        if not (1 / 3 <= ratio <= 3):
            return None
        if 0.87 <= ratio <= 1.15:
            return "1024x1024"

        def _rnd(v: float) -> int:
            return max(1, round(v / 16)) * 16

        if ratio > 1:
            return f"1536x{max(512, min(1536, _rnd(1536 / ratio)))}"
        else:
            return f"{max(512, min(1536, _rnd(1536 * ratio)))}x1536"
    if ratio > 1.15:
        return "1536x1024"
    if ratio < 0.87:
        return "1024x1536"
    return "1024x1024"


def append_endpoint(base_url: str, suffix: str) -> str:
    base = base_url.strip().rstrip("/")
    suffix = suffix.strip()
    if not suffix.startswith("/"):
        suffix = "/" + suffix
    if base.lower().endswith(suffix.lower()):
        return base
    return base + suffix


# ---------- payload builders ----------


def openai_generation_payload(
    req: dict[str, Any], model: dict[str, Any]
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model["model"],
        "prompt": effective_prompt(req),
        "n": 1,
    }
    is_gpt = str(model.get("model") or "").strip().lower().startswith("gpt-image")
    arbitrary = str(model.get("model") or "").strip().lower().startswith("gpt-image-2")
    if is_gpt:
        payload["output_format"] = "png"
    else:
        payload["response_format"] = "b64_json"

    size = (
        _trim_opt(req.get("size"))
        or (
            _trim_opt(req.get("aspect_ratio"))
            and openai_size_from_aspect(str(req.get("aspect_ratio")), arbitrary)
        )
        or _trim_opt(model.get("default_size"))
        or (
            _trim_opt(model.get("default_aspect_ratio"))
            and openai_size_from_aspect(
                str(model.get("default_aspect_ratio")), arbitrary
            )
        )
    )
    if size:
        payload["size"] = size
    q = effective_quality(req, model)
    if q:
        payload["quality"] = q
    return payload


def _xai_resolution(req: dict[str, Any], model: dict[str, Any]) -> str | None:
    for cand in [effective_size(req, model), effective_quality(req, model)]:
        if not cand:
            continue
        norm = cand.strip().lower()
        if norm in ("1k", "2k"):
            return norm
        parsed = parse_pixel_size(norm)
        if parsed:
            w, h = parsed
            return "2k" if max(w, h) > 1536 else "1k"
    return None


def xai_generation_payload(
    req: dict[str, Any], model: dict[str, Any]
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model["model"],
        "prompt": effective_prompt(req),
        "n": 1,
        "response_format": "b64_json",
    }
    aspect = effective_aspect(req, model)
    if not aspect:
        sz = effective_size(req, model)
        if sz:
            parsed = parse_pixel_size(sz)
            if parsed:
                aspect = aspect_from_dimensions(*parsed)
    if aspect:
        payload["aspect_ratio"] = aspect
    res = _xai_resolution(req, model)
    if res:
        payload["resolution"] = res
    return payload


def _is_seedream_v5(model_name: str) -> bool:
    low = (model_name or "").lower()
    return "seedream" in low and ("5.0" in low or "5-0" in low)


def _seedream_min_pixels(model_name: str) -> int:
    """豆包 seedream 5.0 系列 image 生成最小像素要求（官方报错口径）。"""
    return 3686400  # 1920x1920


def enlarge_seedream_size(raw: str | None, model_name: str) -> str | None:
    """豆包专用尺寸放大函数：seedream 5.0 若像素不足 3686400，
    把短边钉到 1920、长边按原比例等比放大取整；合法原样返回。
    解析不出像素时落 1920x1920。仅对 seedream 5.0 生效。"""
    if not raw or not _is_seedream_v5(model_name):
        return _trim_opt(raw)
    s = raw.strip()
    low = s.lower()
    # 档位词 / 无法解析成像素：兜底 1:1 最小合法
    if low in ("1k", "2k", "4k") or "x" not in s:
        return "1920x1920"
    parsed = parse_pixel_size(s)
    if not parsed:
        return "1920x1920"
    w, h = parsed
    if w * h >= _seedream_min_pixels(model_name):
        return f"{w}x{h}"
    short, long_ = (w, h) if w <= h else (h, w)
    k = 1920 / short
    long_scaled = int(round(long_ * k))
    if w <= h:
        return f"1920x{long_scaled}"
    return f"{long_scaled}x1920"


def seedream_generation_payload(
    req: dict[str, Any], provider: dict[str, Any], model: dict[str, Any]
) -> dict[str, Any]:
    model_name = str(model.get("model") or "")
    raw = _trim_opt(req.get("size")) or _trim_opt(model.get("default_size"))
    if not raw:
        raw = "1920x1920" if _is_seedream_v5(model_name) else "2048x2048"
    size = enlarge_seedream_size(raw, model_name)
    payload: dict[str, Any] = {
        "model": model["model"],
        "prompt": effective_prompt(req),
        "response_format": "b64_json",
        "watermark": bool(provider.get("watermark")),
    }
    if _is_seedream_v5(model_name):
        payload["output_format"] = "png"
    if size:
        payload["size"] = size
    # quality mapping for seedream: standard/fast etc via model default
    q = effective_quality(req, model)
    if q:
        payload["quality"] = q
    return payload


def gemini_generation_payload(
    req: dict[str, Any], model: dict[str, Any]
) -> dict[str, Any]:
    rf: dict[str, Any] = {"type": "image", "mime_type": "image/png"}
    size = effective_size(req, model)
    aspect = effective_aspect(req, model)
    if not aspect and size:
        parsed = parse_pixel_size(size)
        if parsed:
            aspect = aspect_from_dimensions(*parsed)
    if aspect:
        rf["aspect_ratio"] = aspect
    if size:
        norm = size.strip().upper()
        if norm in ("512", "1K", "2K", "4K"):
            rf["image_size"] = norm
    return {
        "model": model["model"],
        "input": [{"type": "text", "text": effective_prompt(req)}],
        "response_format": rf,
    }


def comfyui_generation_payload(
    req: dict[str, Any], model: dict[str, Any]
) -> dict[str, Any]:
    # ComfyUI uses workflow JSON injection; for mock we return generic
    return {"prompt": effective_prompt(req), "model": model.get("model") or ""}


# ---------- edit payloads ----------


def _edit_explicit_aspect(req: dict[str, Any]) -> str | None:
    t = _trim_opt(req.get("aspect_ratio"))
    if t:
        return t
    sz = _trim_opt(req.get("size"))
    if sz:
        parsed = parse_pixel_size(sz)
        if parsed:
            return aspect_from_dimensions(*parsed)
    return None


def openai_edit_scalar_fields(
    req: dict[str, Any], model: dict[str, Any]
) -> list[tuple[str, str]]:
    fields = [("model", model["model"]), ("prompt", effective_prompt(req)), ("n", "1")]
    mn = str(model.get("model") or "").lower()
    is_gpt = mn.startswith("gpt-image")
    arbitrary = mn.startswith("gpt-image-2")
    if is_gpt:
        fields.append(("output_format", "png"))
    else:
        fields.append(("response_format", "b64_json"))
    size = _trim_opt(req.get("size")) or (
        _trim_opt(req.get("aspect_ratio"))
        and openai_size_from_aspect(str(req.get("aspect_ratio")), arbitrary)
    )
    if size:
        fields.append(("size", size))
    q = effective_quality(req, model)
    if q:
        fields.append(("quality", q))
    return fields


def xai_edit_payload(
    req: dict[str, Any], model: dict[str, Any], data_urls: list[str]
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": model["model"],
        "prompt": effective_prompt(req),
        "n": 1,
        "response_format": "b64_json",
    }
    if len(data_urls) == 1:
        payload["image"] = {"url": data_urls[0]}
    else:
        payload["images"] = [{"url": u} for u in data_urls]
        payload["aspect_ratio"] = _edit_explicit_aspect(req) or "auto"
    return payload


def seedream_edit_payload(
    req: dict[str, Any],
    provider: dict[str, Any],
    model: dict[str, Any],
    data_urls: list[str],
) -> dict[str, Any]:
    prompt = effective_prompt(req)
    model_name = str(model.get("model") or "")
    raw = _trim_opt(req.get("size"))
    size = enlarge_seedream_size(raw, model_name) if raw else None
    if not raw:
        aspect = _trim_opt(req.get("aspect_ratio"))
        if aspect:
            prompt += f"\n\n画面宽高比：{aspect}"
    payload: dict[str, Any] = {
        "model": model["model"],
        "prompt": prompt,
        "response_format": "b64_json",
        "watermark": bool(provider.get("watermark")),
    }
    if _is_seedream_v5(model_name):
        payload["output_format"] = "png"
    payload["image"] = data_urls[0] if len(data_urls) == 1 else data_urls
    if size:
        payload["size"] = size
    return payload


def gemini_edit_payload(
    req: dict[str, Any], model: dict[str, Any], images: list[dict[str, Any]]
) -> dict[str, Any]:
    rf: dict[str, Any] = {"type": "image", "mime_type": "image/png"}
    aspect = _edit_explicit_aspect(req)
    if aspect:
        rf["aspect_ratio"] = aspect
    sz = _trim_opt(req.get("size"))
    if sz and sz.strip().upper() in ("512", "1K", "2K", "4K"):
        rf["image_size"] = sz.strip().upper()
    items: list[dict[str, Any]] = [{"type": "text", "text": effective_prompt(req)}]
    for im in images:
        items.append(
            {
                "type": "image",
                "mime_type": im["mime"],
                "data": base64.b64encode(im["bytes"]).decode(),
            }
        )
    return {"model": model["model"], "input": items, "response_format": rf}

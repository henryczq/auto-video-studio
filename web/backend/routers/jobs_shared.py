from fastapi import HTTPException


def raise_http_500(exc: Exception):
    raise HTTPException(status_code=500, detail=str(exc))


def run_or_500(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        raise_http_500(exc)

"""Entry point kept at this path because the image runs `uvicorn main:app`.

The application itself lives in the `app` package - see app/main.py.
"""

from app.main import app

__all__ = ["app"]

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)

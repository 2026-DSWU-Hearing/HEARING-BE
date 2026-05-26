import os

os.environ.setdefault("PYTHONIOENCODING", "utf-8")

import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)

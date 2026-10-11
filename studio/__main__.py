def main() -> None:
    import os

    import uvicorn

    host = os.environ.get("STUDIO_HOST", "127.0.0.1")
    port = int(os.environ.get("STUDIO_PORT", "8000"))
    uvicorn.run("studio.main:app", host=host, port=port)


if __name__ == "__main__":
    main()

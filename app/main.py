from app.starter import create_application

app = create_application()

if __name__ == "__main__":
    import uvicorn

    from app.config.config import settings

    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)

import uvicorn

if __name__ == "__main__":
    uvicorn.run("central.app:app", host="127.0.0.1", port=9090, reload=False)

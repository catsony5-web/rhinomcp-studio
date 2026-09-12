FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home control && mkdir /state && chown control:control /state
COPY control_service.py ./
USER 10001:10001
VOLUME /state
EXPOSE 8765
ENTRYPOINT ["python", "control_service.py", "--state", "/state"]

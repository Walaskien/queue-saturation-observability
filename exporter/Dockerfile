FROM python:3.9-slim
WORKDIR /app
COPY queue_exporter.py loadgen.py ./
EXPOSE 9101
USER nobody
ENTRYPOINT ["python", "-u"]
CMD ["queue_exporter.py"]

FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir 'litellm[proxy]'

COPY trajectory_logger.py /app/
COPY litellm_config.yaml /app/
COPY start_proxy.py /app/

RUN mkdir -p /app/trajectories

ENV TRAJECTORY_OUTPUT_DIR=/app/trajectories
ENV LITELLM_PORT=4000
ENV INSTANCE_ID=unknown

EXPOSE 4000

CMD ["python", "start_proxy.py"]
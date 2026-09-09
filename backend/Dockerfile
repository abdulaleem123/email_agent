# FROM python:3.12-slim
# WORKDIR /srv
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt
# COPY . .
# # Run as non-root
# RUN useradd -m appuser && chown -R appuser /srv
# USER appuser

FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Run as non-root
RUN useradd -m appuser && chown -R appuser /srv
USER appuser

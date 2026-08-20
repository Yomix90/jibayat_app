FROM python:3.11-slim

WORKDIR /app

# System dependencies for reportlab (fonts, etc) and pandas (if needed)
RUN apt-get update && apt-get install -y \
    fonts-liberation \
    fonts-dejavu \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create data directory and symlink the database for persistent volumes
RUN mkdir -p /app/data && ln -sf /app/data/fiscalite.db /app/fiscalite.db

# Set environment variables
ENV FLASK_APP=app.py
ENV FLASK_ENV=production

# Expose port
EXPOSE 5000

# Command to run (Initialize DB then start server)
CMD python -c "from database import init_db; init_db()" && gunicorn -w 4 -b 0.0.0.0:5000 app:app

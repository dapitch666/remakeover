FROM python:3.14-slim

WORKDIR /app

# Installation des dépendances
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copie du code de l'application
COPY .streamlit ./.streamlit
COPY app.py .
COPY assets ./assets
COPY locales ./locales
COPY pages ./pages
COPY src ./src
COPY static ./static
COPY VERSION .

# Compile translation catalogs (.po → .mo)
RUN pip install --no-cache-dir babel && \
    pybabel compile -d locales -D rmmanager && \
    pip uninstall -y babel

# Exposition du port Streamlit
EXPOSE 8501

# Commande de démarrage
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]

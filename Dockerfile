# The live Tidewell dashboard, as hosted on Hugging Face Spaces (port 7860).
# Build and run locally:  docker build -t tidewell .  &&  docker run -p 7860:7860 tidewell
# No API key goes in here: the AI analyst runs on each visitor's own key, in their browser.
FROM python:3.12-slim
RUN useradd -m -u 1000 user
WORKDIR /home/user/app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user tidewell ./tidewell
COPY --chown=user web ./web
COPY --chown=user data ./data
USER user
ENV PYTHONUNBUFFERED=1 MPLCONFIGDIR=/tmp/matplotlib
EXPOSE 7860
CMD ["uvicorn", "tidewell.api:app", "--host", "0.0.0.0", "--port", "7860"]

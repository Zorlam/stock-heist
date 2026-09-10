"""
Local dev entrypoint. Run with:

    DATABASE_URL=sqlite:///dev.db python run.py

(or point DATABASE_URL at a real Postgres instance). Not meant for
production serving — use a real WSGI server (gunicorn etc.) for that.
"""

from app.factory import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5000)

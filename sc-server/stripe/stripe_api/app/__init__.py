from flask import Flask

def create_app():
    app = Flask(__name__)

    from app import routes
    app.register_blueprint(routes.bp)

    return app

"""HuggingFace Space entry point for WhaleDecode."""

from whaledecode.adapters.ui.gradio_app import create_gradio_app

app = create_gradio_app()

if __name__ == "__main__":
    app.launch(server_name="0.0.0.0")

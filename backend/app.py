"""
FLASK BACKEND - Legal NLP Contract Analysis
File: backend/app.py
"""

from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import os
import json
from werkzeug.utils import secure_filename

from utils.inference import LegalNLPInferenceAPI
from utils.pdf_extractor import PDFTextExtractor

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------- FLASK INIT ----------------
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "frontend", "templates"),
    static_folder=os.path.join(BASE_DIR, "frontend", "static"),
)

CORS(app)

# ---------------- CONFIG ----------------
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {"pdf", "txt"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ---------------- MODEL INIT ----------------
print("🔥 Loading Legal NLP models...")
MODEL_LOAD_ERROR = None
MODEL_CONFIG_PATH = "models/model_config.json"
MODEL_PATH = "models/best_legal_classifier.pt"

def checkpoint_is_lfs_pointer(path):
    try:
        with open(path, "rb") as f:
            return f.read(80).startswith(b"version https://git-lfs.github.com/spec/v1")
    except OSError:
        return False

try:
    if checkpoint_is_lfs_pointer(MODEL_PATH):
        raise RuntimeError(
            f"{MODEL_PATH} is a Git LFS pointer, not the real checkpoint file."
        )

    api = LegalNLPInferenceAPI(
        model_path=MODEL_PATH,
        config_path=MODEL_CONFIG_PATH,
        device="cpu",  # change to 'cuda' if available
    )
    model_config = api.config
    print("✅ Models loaded successfully!")
except Exception as exc:
    api = None
    MODEL_LOAD_ERROR = str(exc)
    with open(MODEL_CONFIG_PATH, "r", encoding="utf-8") as f:
        model_config = json.load(f)
    print(f"⚠️ Model unavailable: {MODEL_LOAD_ERROR}")

pdf_extractor = PDFTextExtractor()

def require_model():
    if api is not None:
        return None
    return jsonify(
        {
            "success": False,
            "error": "Model is unavailable. Restore backend/models/best_legal_classifier.pt with the real checkpoint file.",
            "details": MODEL_LOAD_ERROR,
        }
    ), 503

# ---------------- HELPERS ----------------
def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_text_from_file(filepath: str) -> str:
    ext = filepath.rsplit(".", 1)[1].lower()
    if ext == "txt":
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    if ext == "pdf":
        return pdf_extractor.extract_text_from_pdf(filepath)
    return ""

# ---------------- HTML ROUTES ----------------
@app.route("/")
def index_page():
    return render_template("index.html")

@app.route("/analyze")
def analyze_page():
    return render_template("analyze.html")

@app.route("/about")
def about_page():
    return render_template("about.html")

# ---------------- API ROUTES ----------------
@app.route("/api/health", methods=["GET"])
def health_check():
    return jsonify(
        {
            "status": "healthy",
            "model_loaded": api is not None,
            "model_error": MODEL_LOAD_ERROR,
            "categories": len(model_config["categories"]),
        }
    )

@app.route("/api/analyze", methods=["POST"])
def analyze_contract():
    try:
        unavailable = require_model()
        if unavailable:
            return unavailable

        contract_text = None

        # Option 1: File upload
        if "file" in request.files:
            file = request.files["file"]

            if file.filename == "":
                return jsonify({"error": "No file selected"}), 400

            if not allowed_file(file.filename):
                return jsonify({"error": "Invalid file type"}), 400

            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
            file.save(filepath)

            contract_text = extract_text_from_file(filepath)
            os.remove(filepath)

        # Option 2: Raw text JSON
        elif request.is_json:
            data = request.get_json()
            contract_text = data.get("text", "")

        else:
            return jsonify({"error": "No file or text provided"}), 400

        if not contract_text or len(contract_text) < 100:
            return jsonify({"error": "Contract text too short"}), 400

        if len(contract_text) > 500_000:
            return jsonify({"error": "Contract text too long"}), 400

        threshold = request.args.get("threshold", 0.4, type=float)
        threshold = max(0.1, min(0.9, threshold))

        print(f"📄 Analyzing contract ({len(contract_text)} chars)")
        result = api.analyze(contract_text, threshold=threshold)
        print("✅ Analysis complete")

        return jsonify({"success": True, "data": result})

    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/classify-clause", methods=["POST"])
def classify_clause():
    try:
        unavailable = require_model()
        if unavailable:
            return unavailable

        data = request.get_json()
        if not data or "text" not in data:
            return jsonify({"error": "No text provided"}), 400

        threshold = data.get("threshold", 0.5)
        predictions = api.quick_classify(data["text"], threshold=threshold)

        return jsonify({"success": True, "predictions": predictions})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/extract-entities", methods=["POST"])
def extract_entities():
    try:
        unavailable = require_model()
        if unavailable:
            return unavailable

        data = request.get_json()
        if not data or "text" not in data:
            return jsonify({"error": "No text provided"}), 400

        entities = api.extract_entities(data["text"])
        return jsonify({"success": True, "entities": entities})

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route("/api/categories", methods=["GET"])
def get_categories():
    return jsonify(
        {
            "success": True,
            "categories": model_config["categories"],
            "total": len(model_config["categories"]),
        }
    )

# ---------------- MAIN ----------------
if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("🚀 LEGAL NLP FLASK API")
    print("=" * 80)
    print(f"📋 Categories: {len(model_config['categories'])}")
    print(f"🤖 Model: {'LegalBERT' if api is not None else 'unavailable'}")
    print("=" * 80)

    app.run(host="127.0.0.1", port=5500, debug=False, use_reloader=False)

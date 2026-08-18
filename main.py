def main():
    print("Hello from repl-nix-workspace!")


if __name__ == "__main__":
    main()
from flask import Flask

app = Flask(__name__)

@app.route('/')
def home():
    return "Memory Test App is running!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)

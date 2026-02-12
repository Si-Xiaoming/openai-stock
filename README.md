# Openai-stock
Based on the demo of Human AI course, our project develops a stock assistant that can answer questions about stock market. It uses the OpenAI API to generate responses based on user input and provides information about stock prices, trends, and other relevant data.

## How to install
### Install Python environment

Make sure you have conda installed. Then create a new conda environment and install the required packages:

```bash
conda create -n openai-stock python=3.13.11
conda activate openai-stock
pip install -r requirements.txt
```

### Install npm packages

Make sure you have Node.js and npm installed. You can download them from [Node.js official website](https://nodejs.org/).
Then, navigate to the `frontend` directory and install the npm packages:

```bash
cd frontend
npm install
```

## How to run

You need to run both the server and the client.
As for the server, navigate to the `backend` directory and run the Flask app:

```bash
cd backend
python app.py
```
The server will start on `http://localhost:5000`.

As for the client, navigate to the `frontend` directory and run the React app:

```bash
cd frontend
npm run dev
```
The client will start on `http://localhost:3000`.


## Quick Start

You can also write a simple script to run both the server and the client at the same time. Create a file named `start.ba` (if you work on Windows) in the root directory of the project with the following content:

```bash
set OPENAI_API_KEY=your_openai_api_key_here

echo Starting Flask Backend...
start "Flask-Backend" cmd /k "cd backend && call conda activate agent && python app.py"

echo Starting Frontend...
start "NPM-Frontend" cmd /k "cd frontend && npm run dev"

echo All systems are starting up...
pause
```
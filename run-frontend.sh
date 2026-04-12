#!/bin/bash
# Run the frontend dev server

cd "$(dirname "$0")"

# Load .env if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

FRONTEND_PORT=${FRONTEND_PORT:-3000}

echo "Starting frontend on http://localhost:$FRONTEND_PORT"
echo "Backend API URL: $NEXT_PUBLIC_API_URL"

cd frontend
PORT=$FRONTEND_PORT npm run dev

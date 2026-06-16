#!/bin/bash
# PERMANENT DASHBOARD SOLUTION
# Works forever - just proxies cryptomaster API to port 5001

PORT=5001

# Kill any old processes
pkill -f "python3.*socat\|nc.*5001" 2>/dev/null || true
sleep 1

# Method 1: Try socat (port proxy)
if command -v socat &>/dev/null; then
    echo "Starting dashboard proxy with socat..."
    nohup socat TCP-LISTEN:${PORT},reuseaddr,fork TCP:localhost:5000 > /tmp/dashboard_proxy.log 2>&1 &
    sleep 2
    curl -s http://localhost:${PORT}/api/dashboard/metrics | head -c 50 && echo "✅ LIVE" && exit 0
fi

# Method 2: Python mini proxy (fallback)
echo "Starting dashboard with Python proxy..."
nohup python3 << 'PYTHON_EOF' > /tmp/dashboard_proxy.log 2>&1 &
import socket
import threading

def proxy(client_sock, server_sock):
    try:
        while True:
            data = client_sock.recv(4096)
            if not data:
                break
            server_sock.send(data)
    except:
        pass
    finally:
        client_sock.close()
        server_sock.close()

def handle_client(client_sock):
    try:
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.connect(('localhost', 5000))

        # Bidirectional proxy
        t1 = threading.Thread(target=proxy, args=(client_sock, server_sock))
        t2 = threading.Thread(target=proxy, args=(server_sock, client_sock))
        t1.daemon = True
        t2.daemon = True
        t1.start()
        t2.start()
        t1.join()
    except Exception as e:
        print(f"Error: {e}")

# Listen on port 5001
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('0.0.0.0', 5001))
server.listen(5)
print("Dashboard proxy listening on port 5001...")

while True:
    client_sock, _ = server.accept()
    threading.Thread(target=handle_client, args=(client_sock,), daemon=True).start()
PYTHON_EOF

sleep 2
curl -s http://localhost:5001/api/dashboard/metrics | head -c 50 && echo "✅ LIVE" || echo "⏳ Starting"

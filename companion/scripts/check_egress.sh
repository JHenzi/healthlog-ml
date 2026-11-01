#!/bin/sh
# Proves R5 at the network level: the database, HealthLog and the Companion can't open a connection to the internet.
# Grafana is left out on purpose (compose.local.yml).
# Connects to 1.1.1.1:443 and sends nothing. Deliberately not a test in Python: tests/privacy can only see sockets
# inside the test process. deploy.sh runs this on every deploy. Exit 1 if any container gets through.
set -eu

failed=0
python_probe='
import socket
s = socket.socket()
s.settimeout(4)
try:
    s.connect(("1.1.1.1", 443))
except OSError:
    raise SystemExit(1)
'
report() {
    if [ "$2" = open ]; then
        echo "FAIL $1 can reach the internet"
        failed=1
    else
        echo "ok   $1 has no route out"
    fi
}

app=$(docker ps -q --filter label=com.docker.compose.service=healthlog | head -1)
for container in healthlog-companion healthlog-companion-jobs "$app"; do
    if docker exec "$container" python -c "$python_probe"; then state=open; else state=closed; fi
    report "$(docker inspect -f '{{.Name}}' "$container")" "$state"
done
if docker exec healthlog-db sh -c 'nc -z -w3 1.1.1.1 443' 2>/dev/null; then state=open; else state=closed; fi
report healthlog-db "$state"
exit "$failed"

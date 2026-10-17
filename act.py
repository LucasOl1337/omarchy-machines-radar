#!/usr/bin/python3
"""Actions the machines panel can run on a configured machine.

    act.py open    ID shell|top|tmux|screen [SESSION [SOCKET]]
    act.py kill    ID PID NAME [TERM|KILL]
    act.py tmux-kill ID SESSION [SOCKET]
    act.py tty-hup ID PID NAME
    act.py unit    ID log|restart UNIT system|user

The panel passes only the machine id and plain values; this script looks up
the ssh alias or adb serial in machines.json and quotes everything itself.
Machines with "readonly": true only open things. Kills check that the PID still has the name the panel showed, so a recycled
PID is never hit. One JSON line goes to stdout: {"ok": bool, "text": "..."}.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

CONFIG = Path(os.environ.get("OMARCHY_MACHINES_CONFIG", Path.home() / ".config/omarchy-machines/machines.json"))
SAFE = re.compile(r"^[\w@%+=:,./ -]{1,200}$")
UNIT = re.compile(r"^[\w@:.\\-]{1,200}\.(service|timer|socket|mount|path|target)$")
PACKAGE = re.compile(r"^[a-zA-Z][\w]*(\.[\w]+)+(:[\w.]+)?$")


def done(ok, text):
    print(json.dumps({"ok": ok, "text": text}, ensure_ascii=False))
    sys.exit(0 if ok else 1)


def machine(machine_id):
    try:
        machines = json.loads(CONFIG.read_text()).get("machines", [])
    except (OSError, ValueError):
        done(False, "cadastro ilegível: " + str(CONFIG))
    for m in machines:
        if m.get("id") == machine_id:
            return m
    done(False, "máquina desconhecida: " + machine_id)


def check(value, pattern=SAFE, what="valor"):
    if not pattern.match(value or ""):
        done(False, "recusado, " + what + " fora do formato aceito")
    return value


def remote(m, script, timeout=20):
    """Run a POSIX sh script on the machine; returns (code, combined output)."""
    if m.get("local"):
        command = ["sh", "-c", script]
    elif m.get("adb"):
        command = ["adb", "-s", m["adb"], "shell", script]
    else:
        command = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", m["ssh"], "sh -c " + shlex.quote(script)]
    try:
        r = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "sem resposta em %d s" % timeout
    except OSError as error:
        return 127, str(error)
    return r.returncode, (r.stdout + r.stderr).strip()


def terminal(argv, title):
    """Open a terminal window detached from the panel."""
    subprocess.Popen(["setsid", "-f", "xdg-terminal-exec", "--title=" + title, *argv],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def ssh_tty(m, command=None):
    base = ["ssh", "-t", m["ssh"]]
    return base + ([command] if command else [])


def open_(m, what, session="", socket_name="default"):
    name = m.get("name", m["id"])
    top = "btop 2>/dev/null || htop 2>/dev/null || top"
    if m.get("adb"):
        serial = m["adb"]
        if what == "screen":
            subprocess.Popen(["setsid", "-f", "scrcpy", "-s", serial, "--window-title=" + name, "--stay-awake"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            done(True, "abrindo a tela de " + name)
        if what == "top":
            terminal(["adb", "-s", serial, "shell", "-t", "top -s 3"], name + " · top")
        else:
            terminal(["adb", "-s", serial, "shell"], name + " · shell")
        done(True, "abrindo " + ("top" if what == "top" else "shell adb") + " em " + name)
    if what == "tmux":
        session = check(session or "radar", what="sessão")
        check(socket_name, what="socket")
        attach = "tmux -L %s new-session -A -s %s" % (shlex.quote(socket_name), shlex.quote(session))
        argv = ["sh", "-c", attach] if m.get("local") else ssh_tty(m, attach)
        terminal(argv, name + " · tmux " + session)
        done(True, "abrindo tmux " + session + " em " + name)
    if what == "top":
        terminal(["sh", "-c", top] if m.get("local") else ssh_tty(m, top), name + " · btop")
        done(True, "abrindo btop em " + name)
    if what == "shell":
        terminal(["bash", "-l"] if m.get("local") else ssh_tty(m), name)
        done(True, "abrindo terminal em " + name)
    done(False, "ação de abrir desconhecida: " + what)


def kill(m, pid, name, signal="TERM"):
    if not pid.isdigit() or int(pid) <= 2:
        done(False, "PID inválido")
    if signal not in ("TERM", "KILL"):
        done(False, "sinal inválido")
    check(name, what="nome")
    if m.get("adb"):
        package = name.split(":")[0]
        if PACKAGE.match(name):
            code, out = remote(m, "am force-stop " + shlex.quote(package))
            done(code == 0, ("app " + package + " fechado") if code == 0 else (out or "am force-stop falhou"))
        script = 'kill -%s %s' % (signal, pid)
        code, out = remote(m, script)
        done(code == 0, ("%s (%s) encerrado" % (name, pid)) if code == 0 else "sem permissão: no celular só dá pra fechar apps e processos do shell")
    script = """
p=%(pid)s; n=%(name)s; s=%(sig)s
c=$(cat /proc/$p/comm 2>/dev/null) || { echo "já tinha saído"; exit 3; }
[ "$c" = "$n" ] || { echo "o PID $p agora é $c, não $n: nada feito"; exit 4; }
kill -s $s $p 2>/dev/null || sudo -n kill -s $s $p 2>/dev/null || { echo "sem permissão pra encerrar $n ($p)"; exit 5; }
alive() { [ "$(cat /proc/$p/comm 2>/dev/null)" = "$n" ] && ! grep -q '^State:[[:space:]]*Z' /proc/$p/status 2>/dev/null; }
i=0; while [ $i -lt 15 ] && alive; do sleep 0.2; i=$((i+1)); done
if alive; then echo "SIG$s enviado, $n ($p) ainda rodando"; exit 6; fi
echo "$n ($p) encerrado"
""" % {"pid": pid, "name": shlex.quote(name), "sig": signal}
    code, out = remote(m, script)
    lines = out.strip().splitlines()
    done(code == 0, lines[-1] if lines else "saída %d" % code)


def tmux_kill(m, session, socket_name="default"):
    check(session, what="sessão")
    check(socket_name, what="socket")
    code, out = remote(m, "tmux -L %s kill-session -t %s" % (shlex.quote(socket_name), shlex.quote("=" + session)))
    done(code == 0, ("sessão tmux " + session + " encerrada") if code == 0 else (out or "tmux falhou"))


def tty_hup(m, pid, name):
    """Hang up a terminal: SIGHUP to its session leader, like closing the window."""
    if not pid.isdigit() or int(pid) <= 2:
        done(False, "PID inválido")
    check(name, what="nome")
    script = """
p=%(pid)s; n=%(name)s
c=$(cat /proc/$p/comm 2>/dev/null) || { echo "terminal já fechado"; exit 3; }
[ "$c" = "$n" ] || { echo "o PID $p agora é $c: nada feito"; exit 4; }
kill -HUP $p 2>/dev/null || sudo -n kill -HUP $p 2>/dev/null || { echo "sem permissão"; exit 5; }
echo "terminal de $n ($p) fechado"
""" % {"pid": pid, "name": shlex.quote(name)}
    code, out = remote(m, script)
    lines = out.strip().splitlines()
    done(code == 0, lines[-1] if lines else "saída %d" % code)


def unit(m, verb, name, scope):
    check(name, UNIT, "unidade")
    if scope not in ("system", "user") or verb not in ("log", "restart"):
        done(False, "pedido inválido")
    user = " --user" if scope == "user" else ""
    if verb == "log":
        command = "journalctl%s -u %s -n 200 -f" % (user, shlex.quote(name))
        terminal(["sh", "-c", command] if m.get("local") else ssh_tty(m, command), m.get("name", m["id"]) + " · " + name)
        done(True, "abrindo o log de " + name)
    sudo = "" if scope == "user" else 'S=; [ "$(id -u)" = 0 ] || S="sudo -n"; $S '
    script = "%ssystemctl%s restart %s && sleep 1 && systemctl%s is-active %s" % (sudo, user, shlex.quote(name), user, shlex.quote(name))
    code, out = remote(m, script, timeout=60)
    state = (out.strip().splitlines() or ["?"])[-1]
    done(code == 0, name + (" reiniciado: " + state if code == 0 else " não reiniciou: " + state))


CHANGES = {"kill", "tmux-kill", "tty-hup"}


def main(argv):
    if len(argv) < 3:
        done(False, __doc__.strip().splitlines()[2])
    verb, m = argv[1], machine(argv[2])
    args = argv[3:]
    # A shared host (someone else's server) is watch-only: open things, never stop them.
    if m.get("readonly") and (verb in CHANGES or (verb == "unit" and args[:1] == ["restart"])):
        done(False, m.get("name", m["id"]) + " é só leitura no radar")
    if verb == "open" and args:
        open_(m, args[0], args[1] if len(args) > 1 else "", args[2] if len(args) > 2 else "default")
    if verb == "kill" and len(args) >= 2:
        kill(m, args[0], args[1], args[2] if len(args) > 2 else "TERM")
    if verb == "tmux-kill" and args:
        tmux_kill(m, args[0], args[1] if len(args) > 1 else "default")
    if verb == "tty-hup" and len(args) >= 2:
        tty_hup(m, args[0], args[1])
    if verb == "unit" and len(args) >= 3:
        unit(m, args[0], args[1], args[2])
    done(False, "pedido inválido")


if __name__ == "__main__":
    main(sys.argv)

# Radar de máquinas

O uso de cada máquina sua (PC, notebook e VPS) na barra do Omarchy, um card por máquina, no mesmo formato do [Radar 9Router](https://github.com/LucasOl1337/omarchy-9router-radar).

O ícone de servidor abre uma grade com CPU, RAM, o disco mais cheio e swap, cada barra verde, amarela ou vermelha, um gráfico da última hora e os avisos que pedem atenção: disco acima de 85% (só amarelo; disco enchendo nunca acende vermelho), memória acima de 90%, carga alta, steal de VPS disputada, serviços do systemd falhando e containers sem saúde. O ícone acende quando alguma VPS não responde ou tem aviso vermelho.

![Visão geral com um card por máquina](docs/visao-geral.png)

Clicar num card abre o detalhe: processos que mais gastam CPU e memória (agrupados pelo nome), containers do Docker, agentes de IA abertos, GPU, discos, rede e IO. A aba Tailnet lista todos os aparelhos da sua rede Tailscale, com o caminho de cada um (direto ou relay).

No detalhe dá pra agir na máquina:

- **Terminal**, **tmux** (entra ou cria a sessão `radar`, que sobrevive se a janela fechar), **btop** e copiar o comando de acesso.
- **Terminais abertos**: cada pseudo-terminal com dono, o programa da frente (agente marcado em negrito), há quanto tempo está parado e aberto. *Parar* manda SIGTERM só no programa da frente; *fechar* manda SIGHUP no terminal inteiro.
- **Sessões tmux** de todos os sockets do usuário, com *entrar* e *encerrar*.
- **Processos** um a um, com filtro por nome: *encerrar* (SIGTERM) e *matar* (SIGKILL).
- **Serviços falhando**: *log* abre o `journalctl -f` numa janela e *reiniciar* reinicia a unidade.

Tudo que encerra ou reinicia pede um segundo clique em até 4 s. As ações passam por `act.py` com argumentos simples: ele acha a máquina no cadastro, monta o comando sem shell do painel e confere que o PID ainda tem o nome mostrado, então um PID reciclado nunca é atingido. Máquina com `"readonly": true` (servidor dividido com outra equipe, por exemplo) só observa e abre terminais.

Celular Android entra pelo `adb`: CPU, RAM, swap, armazenamento, bateria e apps. Os botões abrem `adb shell`, `top` e a tela pelo `scrcpy`; *fechar app* usa `am force-stop`.

Máquinas sem SSH entram pela API do provedor, só pra observar:

- **Nó de Docker Swarm pelo Portainer**: CPU, RAM, carga, pressão e disco do próprio nó (lidos de dentro de um container que já roda nele, porque `/proc` e a raiz são do host), os serviços do nó com a memória de cada um e as tarefas que deviam rodar e não rodam. Com token da Hetzner Cloud, a rede vem das métricas dela. Os nós de um mesmo cluster dividem um chip (`group`) que abre só os cards deles.
- **Projeto Railway**: vCPU e memória usados contra o limite dos serviços no ar, rede, volumes como discos e cada serviço com o estado do último deploy; deploy que falhou nas últimas 24 h vira aviso.

![Detalhe de uma VPS](docs/detalhe.png)

Novidades de cada versão em [docs/releases](docs/releases/).

## Instalar

Requer Omarchy com Quickshell e plugins, Python 3 e systemd do usuário. Nas máquinas remotas basta `python3` e acesso SSH sem senha interativa (chave no agente ou sem passphrase). Nada é instalado nelas. Tailscale, Docker e `nvidia-smi` são opcionais. Node.js é necessário só pra rodar os testes do modelo.

```bash
git clone https://github.com/LucasOl1337/omarchy-machines-radar.git
cd omarchy-machines-radar
mkdir -p ~/.config/omarchy-machines
cp machines.example.json ~/.config/omarchy-machines/machines.json
# Edite o arquivo com suas máquinas.
python3 install.py
```

Cada máquina do cadastro tem:

- `id` e `name`: identificador e nome no painel.
- `local: true` pra máquina onde a barra roda, ou `ssh` com um alias do `~/.ssh/config` (ou `usuario@host`).
- `provider` e `role` (opcionais): selo do provedor e uma linha dizendo pra que a máquina serve.
- `kind` (opcional): `local` pra notebook ou desktop. Desligado vira cinza, sem alarme. VPS fora do ar fica vermelha.
- `tailnet` (opcional): nome do aparelho no Tailscale, quando difere do hostname.
- `adb` (em vez de `ssh`): serial do celular Android no `adb devices`, por exemplo `IP:5555`. Use com `kind: "local"`, pra celular desligado não virar alarme.
- `readonly` (opcional): `true` esconde encerrar, matar e reiniciar; o radar só observa.
- `portainer` (em vez de `ssh`): `{"env": "PREFIXO", "node": "hostname do nó", "endpoint": 1}`. O radar lê `PREFIXO_PORTAINER_URL`, `PREFIXO_PORTAINER_TOKEN` e, se houver, `PREFIXO_HCLOUD_TOKEN` (rede).
- `railway` (em vez de `ssh`): `{"project": "nome ou id", "environment": "production"}`; sem `project`, soma todos os projetos que o token vê. Token de conta em `RAILWAY_TOKEN` (token de workspace não lista projetos).
- `group` (opcional): nome do cluster; máquinas com o mesmo grupo viram um chip só.

Tokens das máquinas por API ficam em `~/.config/omarchy-machines/secrets.env` (`CHAVE=valor`, modo 0600), nunca no cadastro. Os tokens só precisam de leitura: o radar não reinicia nem para nada por API.

Sem cadastro, o radar usa o `machines.example.json`.

## Como lê

A cada minuto o timer roda `collect.py`, que manda `probe.py` pela entrada padrão de `ssh ALIAS python3 -` pra todas as máquinas em paralelo (só biblioteca padrão; na máquina local roda direto). O probe mede CPU, IO e rede numa janela de um segundo em `/proc` e lê memória, discos, temperatura, `docker ps`/`docker stats`, `systemctl --failed`, `nvidia-smi`, `tailscale ip`, os pseudo-terminais em `/proc` e `tmux list-sessions`. Processos vão só pelo nome, nunca pela linha de comando. O celular é lido por `android.py` numa única chamada `adb shell`, e as máquinas por API por `cloud.py` (Portainer: um `exec` de `sh` com `/proc/stat` duas vezes, `meminfo`, `loadavg`, `df` e PSI num container do nó; Railway: GraphQL de projetos e métricas). Uma máquina sem resposta mantém a última leitura boa, marcada com a idade e o erro.

Disco que guarda imagens montadas em loop (um disco por pessoa numa VPS dividida, por exemplo) conta o espaço delas como reservado, não usado: a porcentagem e o alarme olham só a parte do sistema, e cada imagem aparece como disco próprio.

Processos aparecem só pelo nome curto (`comm`), nunca pela linha de comando, pra não vazar argumentos e tokens. O estado não guarda senhas nem variáveis de ambiente.

## Arquivos e operação

- Fonte: diretório do clone deste repositório.
- Plugin ativo: `~/.config/omarchy/plugins/lol.machines/`.
- Cadastro: `~/.config/omarchy-machines/machines.json`.
- Tokens das máquinas por API: `~/.config/omarchy-machines/secrets.env`, modo 0600 (ou o caminho em `OMARCHY_MACHINES_SECRETS`).
- Estado: `~/.local/state/omarchy-trackers/machines/status.json`, modo 0600, com cerca de uma hora de histórico.
- Timer: `omarchy-machines.timer`, uma leitura por minuto depois da anterior.

```bash
python3 install.py
systemctl --user status omarchy-machines.timer
systemctl --user start omarchy-machines.service
node --test tests/test_model.cjs
python3 -m unittest discover -s tests -v
```

O instalador publica a interface em `.runtime/<hash>/` e troca o manifesto depois de copiar todos os imports. Isso evita que a barra mantenha QML antigo em cache durante uma atualização.

Clique no ícone pra abrir; botão do meio ou R atualizam e Esc fecha. Setas ← → trocam de aba, 0 a 9 escolhem direto (0 é Todas), T abre a Tailnet e ↑ ↓ rolam. A aba fica lembrada em `~/.local/state/omarchy-trackers/machines/view.json`.

Pra conferir o que a barra carregou:

```bash
quickshell ipc -p /usr/share/omarchy/shell call lol.machines diagnostics
quickshell ipc -p /usr/share/omarchy/shell call lol.machines select vps1
```

Licença MIT.

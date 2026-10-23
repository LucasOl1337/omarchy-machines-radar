# Radar de máquinas v1.3.0

23 de outubro de 2026

Junta o que entrou desde a v1.0.1 (1.1.0, 1.1.1 e 1.2.0, que não ganharam release própria) e a aba Total.

![Aba Total](https://github.com/LucasOl1337/omarchy-machines-radar/releases/download/v1.3.0/release.png)

## Novidades

- **Aba Total.** Soma todas as máquinas no ar: núcleos de CPU em uso de quantos existem, RAM e disco, com o que sobra livre. Mostra o uso somado da última hora (cada máquina pesa pelo tamanho) e uma linha por máquina, a de mais núcleos livres primeiro. Railway (limite de plano), celular e máquina desligada ficam fora da soma, listados embaixo. A folga só nas máquinas que não são `readonly` aparece à parte. A tecla `1` abre a aba.
- **Máquinas por API, sem SSH.** Nó de Docker Swarm pelo Portainer: CPU, RAM, carga, pressão e disco do nó, lidos de dentro de um container que já roda nele. Também os serviços do nó e as tarefas que deviam rodar e não rodam, e a rede pela Hetzner Cloud quando tem token. Projeto Railway: vCPU e memória contra o limite, volumes como discos e o estado do último deploy de cada serviço. Os nós de um cluster dividem um chip (`group`). Os tokens ficam em `~/.config/omarchy-machines/secrets.env`, fora do cadastro.
- **Ações no detalhe (1.1.0).** Mostra os terminais abertos, com parar e fechar, as sessões tmux de todos os sockets, com entrar e encerrar, e os processos um a um, com filtro, encerrar e matar. Serviços falhando ganham log e reiniciar. Tudo que encerra pede segundo clique.
- **Celular Android por adb (1.1.0).** CPU, RAM, armazenamento, bateria e apps, com `adb shell`, `top`, tela pelo `scrcpy` e fechar app.
- **Máquina `readonly` (1.1.0).** Para servidor dividido: só observa e abre terminais.

## Correções

- **Swap segue a pressão de memória (1.1.1).** Swap cheia com páginas paradas não acende mais alarme. O aviso vem da pressão de memória (PSI) ou de swap cheia com menos de 10% de RAM livre.
- **Disco enchendo só fica amarelo.** O aviso de disco sai a partir de 85% e nunca fica vermelho.

## Atualizar

```bash
git pull && python3 install.py
```

Para máquinas por API, ver `machines.example.json` e a seção de cadastro do README.

## Verificado

Passaram 13 testes Python e 18 testes Node. A aba Total foi conferida numa bancada com o estado real e com um estado anonimizado (a imagem acima). A soma do painel bate com a do `maquinas.py --total` da skill. A barra carregou a 1.3.0, conferido pelo diagnóstico IPC.

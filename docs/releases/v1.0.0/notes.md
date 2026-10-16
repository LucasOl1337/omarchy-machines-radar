# Radar de máquinas v1.0.0

16 de outubro de 2026

O uso do seu PC, notebook e VPS na barra do Omarchy, um card por máquina, no mesmo formato do Radar 9Router.

## O que vem

- **Um card por máquina.** CPU, RAM, o disco mais cheio e swap com barras verdes, amarelas ou vermelhas, gráfico de CPU e RAM da última hora e os avisos que pedem atenção.
- **Avisos que importam.** Disco acima de 85%, memória acima de 90%, swap, carga acima de 1,5 por núcleo, steal de VPS disputada, temperatura, serviços do systemd falhando (agrupados) e containers sem saúde. O ícone da barra acende quando uma VPS some ou tem aviso vermelho; notebook desligado fica cinza.
- **Detalhe ao clicar.** Processos que mais gastam CPU e memória, agrupados pelo nome, containers do Docker, agentes de IA abertos, GPU, todos os discos, rede e IO.
- **Gestão rápida.** Botões pra abrir um terminal com `ssh` na máquina, abrir o `btop` dela ou copiar o comando.
- **Aba Tailnet.** Todos os aparelhos da rede Tailscale, com caminho direto ou relay e a máquina cadastrada correspondente.
- **Nada instalado nos servidores.** O probe vai pela entrada padrão de `ssh ALIAS python3 -`, só com biblioteca padrão. Processos aparecem só pelo nome curto, nunca pela linha de comando.

## Instalar

```bash
git clone https://github.com/LucasOl1337/omarchy-machines-radar.git
cd omarchy-machines-radar
mkdir -p ~/.config/omarchy-machines
cp machines.example.json ~/.config/omarchy-machines/machines.json
# Cadastre suas máquinas antes de instalar.
python3 install.py
```

A imagem usa dados fictícios.

## Verificado

5 testes Python e 6 testes Node passaram. Plugin validado, painel renderizado com dados reais e fictícios numa bancada, e versão carregada na barra conferida por diagnóstico IPC, com cinco máquinas reais (PC, três VPS e um notebook desligado).

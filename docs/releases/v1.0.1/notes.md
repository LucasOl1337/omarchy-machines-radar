# Radar de máquinas v1.0.1

16 de outubro de 2026

## Correções

- **Disco dividido por imagens não é mais disco cheio.** Numa VPS em que cada pessoa tem um disco próprio montado de uma imagem pré-alocada, a raiz parecia em 92% e acendia o alarme. O probe agora reconhece os loops com arquivo de imagem e conta esse espaço como reservado: a raiz mostra só a parte do sistema (`141 / 211 GB + 660 GB reservados pra lucas e alonso`, 67%), e cada imagem aparece como disco próprio, com o próprio uso.

## Atualizar

```bash
git pull && python3 install.py
```

## Verificado

5 testes Python e 7 testes Node passaram, incluindo o caso da VPS dividida. Probe conferido numa VPS real com duas imagens de 330 GB, painel renderizado numa bancada e versão carregada na barra conferida por diagnóstico IPC.

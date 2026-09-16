# Terceiros

O Spectra é distribuído sob a [licença MIT](LICENSE). Este arquivo lista o que ele
usa de terceiros, cada um sob a própria licença.

Nada de terceiros é versionado neste repositório.

## Dependências

| Biblioteca | Licença | Para quê |
|---|---|---|
| numpy | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | motor de renderização |
| psutil | BSD-3-Clause | processos e sensores |
| pywebview | BSD 3-Clause | janela que hospeda a interface |
| pystray | LGPLv3 | ícone na bandeja |
| Pillow | MIT-CMU | ícone e imagem |
| pyaudiowpatch | Apache-2.0 | captura de áudio para os efeitos reativos |
| dxcam | MIT | captura de tela para os efeitos de ambilight |
| pythonnet | MIT | leitura de sensores no Windows |

Lido dos metadados dos pacotes instalados, não de memória.

O **pystray** é LGPL v3. Ele é usado sem modificação, como biblioteca, e pode ser
substituído por outra versão compatível.

## OpenRGB

O Spectra fala o protocolo do servidor SDK do [OpenRGB](https://openrgb.org), que é
GPLv2. **Nada do OpenRGB é distribuído aqui**: ele é um programa separado, instalado
por você, e a conversa acontece por socket TCP. Comunicação entre processos por rede
não é vinculação, então a GPL do OpenRGB não alcança este código.

A implementação do protocolo neste repositório, em `spectra/core/protocol.py`, foi
escrita do zero a partir da documentação pública do formato.

## Qt

O Spectra **não** usa Qt. A interface é HTML e JavaScript servidos localmente dentro
de uma janela do pywebview, que no Windows usa o WebView2 do próprio sistema.

# Hospedagem

O app não guarda os arquivos enviados: os dados ficam na memória da sessão e são descartados quando ela
termina. Qualquer instituição pode hospedá-lo de uma das formas abaixo.

## Streamlit Community Cloud (gratuito, sem servidor)

1. Publique o repositório no GitHub. No VS Code: Controle do Código-Fonte → “Publicar no GitHub”.
2. Entre em <https://share.streamlit.io> com a conta do GitHub e clique em **Create app**.
3. Escolha o repositório, a branch `main` e o arquivo `app.py`. Em **App URL**, escolha o endereço
   (ex.: `segmentos-criticos.streamlit.app`).
4. Em **Advanced settings**, selecione **Python 3.13** (o padrão, 3.12, também funciona) e clique em **Deploy**.

Cada envio para a branch `main` atualiza o app. Sem acessos por 12 horas, o app hiberna; quem abrir o link
clica em “Yes, get this app back up!” e ele volta. O limite é de cerca de 2 núcleos e 2,7 GB de memória.

## Servidor próprio com Docker (ex.: OptiPlex do laboratório)

Em um Ubuntu Server 24.04 LTS com acesso à internet:

```bash
sudo apt update && sudo apt install -y git
curl -fsSL https://get.docker.com | sudo sh     # script oficial de instalação do Docker
sudo usermod -aG docker $USER                   # saia e entre de novo na sessão
git clone https://github.com/<usuario>/<repositorio>.git
cd <repositorio>
docker compose up -d --build
```

O app fica em <http://localhost:8501> e volta sozinho depois de reinícios e quedas de energia.

| Tarefa | Comando |
| --- | --- |
| Atualizar para a versão do GitHub | `git pull && docker compose up -d --build` |
| Ver o registro | `docker compose logs -f` |
| Parar | `docker compose down` |

Por padrão o app só responde na própria máquina. Para abrir na rede do laboratório, troque em `compose.yaml`
`"127.0.0.1:8501:8501"` por `"8501:8501"`.

### Endereço público sem abrir portas

- **Tailscale Funnel** (gratuito, endereço fixo `https://<máquina>.<rede>.ts.net`). Na primeira vez, o
  comando mostra um link para autorizar o Funnel na conta.

  ```bash
  curl -fsSL https://tailscale.com/install.sh | sh
  sudo tailscale up
  sudo tailscale funnel --bg 8501
  ```

- **Cloudflare Tunnel**: endereço fixo exige um domínio na Cloudflare. Para um teste rápido,
  `cloudflared tunnel --url http://localhost:8501` gera um endereço temporário.

Os dois usam só conexões de saída, mas a rede é da universidade: combine com a equipe de TI antes de publicar.

## Sem Docker

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m streamlit run app.py --server.headless true
```

Para manter no ar, crie um serviço do systemd que rode o último comando.

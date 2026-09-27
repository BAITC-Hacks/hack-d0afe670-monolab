# GovTech VPS Deploy (MonoLab)

**Live site:** https://monolab.govtech-kz.com (port **8016**)

## Quick redeploy from laptop

```bash
VPS_PASSWORD='your-ssh-password' ./deploy/vps/deploy.sh
```

## Manual start on server

```bash
ssh monolab@82.115.43.223
systemctl --user start docker
cd ~/talap && docker compose up -d
~/talap/deploy/vps/start.sh   # or nohup ... &
```

## Logs

```bash
tail -f ~/talap/talap.log
```

## Notes

- Rootless Docker must be running (`systemctl --user start docker`)
- 4 GB disk quota — uses CPU-only PyTorch (no CUDA wheels)
- Model weights: `backend/training/weights/best.pt` (rsync'd on deploy)
- DB: Postgres in Docker, seeded from local `pg_dump` on deploy

- ensure git lfs is installed

```bash
sudo pacman -S git-lfs
```

- ensure git is configured before using

```bash
git config --global init.defaultBranch main
git config --global user.email "orion@orion.local"
git config --global user.name "orion"
```

- use ubuntu jammy64 or higher for higher python and pip version to avoid building packages from source
- for torch and torchvision without cuda use `--index-url https://download.pytorch.org/whl/cpu` with pip install command


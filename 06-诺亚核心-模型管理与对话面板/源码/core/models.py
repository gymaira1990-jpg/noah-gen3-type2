"""诺亚核心 · 模型 CRUD"""
from .kernel import Config, ModelConfig, save_config

def add_model(cfg: Config, model: ModelConfig) -> ModelConfig:
    for i, m in enumerate(cfg.models):
        if m.name == model.name:
            cfg.models[i] = model
            save_config(cfg)
            return model
    cfg.models.append(model)
    save_config(cfg)
    return model

def remove_model(cfg: Config, name: str) -> bool:
    for i, m in enumerate(cfg.models):
        if m.name == name:
            cfg.models.pop(i)
            save_config(cfg)
            return True
    return False

def get_model(cfg: Config, name: str) -> ModelConfig | None:
    for m in cfg.models:
        if m.name == name:
            return m
    return None

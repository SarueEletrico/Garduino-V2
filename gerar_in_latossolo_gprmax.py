import math
import random
import json
import os
from datetime import datetime

# Constante
C = 299792458.0  # m/s

# ---------- Amostradores e propriedades ----------
def sample_uniform(a, b):
    return random.uniform(a, b)

LATOSSOLO_HORIZONTES = {
    "latossolo_A":         lambda: {"er": sample_uniform(5.0,  10.0), "sigma": sample_uniform(0.001,  0.01)},
    "latossolo_Bw":        lambda: {"er": sample_uniform(12.0, 18.0), "sigma": sample_uniform(0.01,  0.025)},
    "latossolo_C":         lambda: {"er": sample_uniform(15.0, 25.0), "sigma": sample_uniform(0.02,   0.05)},
    "latossolo_transicao": lambda: {"er": sample_uniform(10.0, 13.0), "sigma": sample_uniform(0.01,  0.015)},
}

# ---------- Perfil e interfaces ----------
def gerar_perfil_latossolo(esp_A_min=0.1, esp_A_max=0.4,
                           esp_B_min=0.5, esp_B_max=1.5):
    """Retorna ordem dos horizontes, espessuras e slopes (inclinação em rad)."""
    ordem = ["latossolo_A", "latossolo_Bw", "latossolo_C"]
    esp_A  = random.uniform(esp_A_min, esp_A_max)
    esp_Bw = random.uniform(esp_B_min, esp_B_max)
    esp_C  = 2.0  # suficientemente espessa para preencher o restante do domínio
    espessuras = [esp_A, esp_Bw, esp_C]
    angulos = [random.uniform(-7, 7) for _ in range(3)]
    slopes  = [math.tan(math.radians(a)) for a in angulos]
    return ordem, espessuras, slopes


def gerar_boxes_latossolo(ordem, espessuras, slopes,
                          domain_x=1.0, topo_solo=1.6):
    """Cria funções de interface y(x) para cada horizonte.

    O eixo y é a direção vertical (profundidade crescente para baixo).
    Os horizontes variam ao longo de y; a inclinação leve (slopes) introduz
    variação suave ao longo de x para tornar as amostras mais realistas.
    """
    interfaces = []
    x_ref  = domain_x / 2.0
    y_atual = topo_solo
    for i in range(len(ordem)):
        m           = slopes[i]
        y_intercept = y_atual

        def interface_fn(x, y0=y_intercept, slope=m, xr=x_ref):
            return y0 + slope * (x - xr)

        interfaces.append(interface_fn)
        y_atual -= espessuras[i]
    return interfaces


def discretizar_latossolo(ordem, interfaces,
                          nx=20,
                          domain_x=1.0,
                          domain_z=1.0,
                          domain_y=2.0):
    """Gera a lista de blocos (#box) para cada fatia em x.

    Os horizontes variam ao longo de y (profundidade).
    O domínio é 1 m × 2 m × 1 m (x × y × z).
    """
    blocos = []
    dx = domain_x / nx
    for i in range(nx):
        x1    = i * dx
        x2    = (i + 1) * dx
        x_mid = (x1 + x2) / 2.0
        for j in range(len(ordem)):
            material = ordem[j]
            y_topo   = interfaces[j](x_mid)
            y_base   = interfaces[j + 1](x_mid) if j + 1 < len(interfaces) else 0.0
            y_topo   = max(0.0, min(domain_y, y_topo))
            y_base   = max(0.0, min(domain_y, y_base))
            if y_topo > y_base:
                blocos.append({
                    "material": material,
                    "x1": x1,    "x2": x2,
                    "y1": y_base, "y2": y_topo,
                    "z1": 0.0,    "z2": domain_z,
                })
    return blocos

# ---------- Materiais ----------
def gerar_materials(ordem, include_transicao=False):
    materiais = {}
    for mat in ordem:
        materiais[mat] = LATOSSOLO_HORIZONTES[mat]()
    if include_transicao:
        materiais["latossolo_transicao"] = LATOSSOLO_HORIZONTES["latossolo_transicao"]()
    return materiais

# ---------- Utilitários ----------
def velocidade_media(materiais):
    ers = [p["er"] for p in materiais.values() if p.get("er") is not None]
    if not ers:
        return C
    er_mean = sum(ers) / len(ers)
    return C / math.sqrt(er_mean)


def dt_recomendado(dx, dy, dz, safety_factor=0.99):
    inv2   = (1.0 / dx**2) + (1.0 / dy**2) + (1.0 / dz**2)
    dt_max = 1.0 / (C * math.sqrt(inv2))
    return dt_max * safety_factor


def validar_time_window(time_window_s, domain_depth, vel_media):
    t_two_way = 2.0 * domain_depth / vel_media
    ok = time_window_s >= t_two_way
    return ok, t_two_way

# ---------- Escrita do .in (comandos gprMax iniciando com '#') ----------
def escrever_in_gprmax(filename,
                       materiais,
                       blocos,
                       domain_x=1.0, domain_y=2.0, domain_z=1.0,
                       dx_val=0.05, dy_val=0.05, dz_val=0.05,
                       time_window_s=70e-9,
                       waveform_cmd="ricker 1 400e6 my_ricker",
                       hertzian_cmd="y 0.30 1.80 0.50 my_ricker",
                       rx_cmd="0.70 1.80 0.50",
                       title="Latossolo_sim"):
    """Escreve o arquivo de entrada (.in) para o gprMax.

    Domínio: 1 m (x) × 2 m (y) × 1 m (z).
    Os horizontes de solo variam ao longo do eixo y (profundidade).
    Fonte e receptor estão posicionados na superfície do solo (y ≈ 1.80 m),
    centrados em z = 0.50 m e separados em x (0.30 m e 0.70 m).
    """
    now            = datetime.now().isoformat()
    dt_rec         = dt_recomendado(dx_val, dy_val, dz_val)
    dt_ns          = dt_rec * 1e9
    time_window_ns = time_window_s * 1e9

    with open(filename, "w", encoding="utf-8", newline="\n") as f:
        f.write("## gprMax input generated by gerar_in_latossolo_gprmax.py\n")
        f.write(f"## Title: {title}\n")
        f.write(f"## Generated: {now}\n\n")

        f.write("## ---------- DOMAIN / MESH / TIME ----------\n")
        f.write(f"#domain: {domain_x:.6f} {domain_y:.6f} {domain_z:.6f}\n")
        f.write(f"#dx_dy_dz: {dx_val:.6e} {dy_val:.6e} {dz_val:.6e}\n")
        f.write(f"#time_window: {time_window_ns:.6e}\n")
        f.write(f"## Recommended dt (CFL) = {dt_ns:.6e} ns\n")
        f.write(f"##dt: {dt_ns:.6e}\n\n")

        f.write("## ---------- SOURCE / RECEIVER ----------\n")
        f.write(f"#waveform: {waveform_cmd}\n")
        f.write(f"#hertzian_dipole: {hertzian_cmd}\n")
        f.write(f"#rx: {rx_cmd}\n\n")

        f.write("## ---------- MATERIALS ----------\n")
        f.write("## Format: #material: <er> <conductivity> <permeability> <magconductivity> <id>\n")
        for mat_name, props in materiais.items():
            er    = props["er"]
            sigma = props["sigma"]
            f.write(f"#material: {er:.4f} {sigma:.6f} 1.0 0.0 {mat_name}\n")
        f.write("\n")

        f.write("## ---------- GEOMETRY (boxes) ----------\n")
        f.write("## Format: #box: <x1> <y1> <z1> <x2> <y2> <z2> <material>\n")
        f.write("## Horizons vary along y (depth); x and z span 1 m each.\n")
        for bloco in blocos:
            m = bloco["material"]
            f.write(
                f"#box: {bloco['x1']:.6f} {bloco['y1']:.6f} {bloco['z1']:.6f} "
                f"{bloco['x2']:.6f} {bloco['y2']:.6f} {bloco['z2']:.6f} {m}\n"
            )
        f.write("\n")

        f.write("## ---------- END ----------\n")

# ---------- Geração de múltiplas simulações ----------
def gerar_dataset(n_amostras=100,
                  output_dir="simulacoes_latossolo",
                  prefix="latossolo_sim",
                  domain_x=1.0, domain_y=2.0, domain_z=1.0,
                  dx_val=0.05, dy_val=0.05, dz_val=0.05,
                  topo_solo=1.6,
                  time_window_s=70e-9):
    """Gera *n_amostras* arquivos .in para o gprMax e salva os labels em JSON.

    Labels contêm as espessuras reais das camadas A e Bw, usadas como
    alvos de regressão na rede neural.
    """
    os.makedirs(output_dir, exist_ok=True)
    labels = []

    for i in range(n_amostras):
        ordem, espessuras, slopes = gerar_perfil_latossolo()
        materiais  = gerar_materials(ordem)
        interfaces = gerar_boxes_latossolo(ordem, espessuras, slopes,
                                           domain_x=domain_x,
                                           topo_solo=topo_solo)
        blocos     = discretizar_latossolo(ordem, interfaces,
                                           nx=20,
                                           domain_x=domain_x,
                                           domain_z=domain_z,
                                           domain_y=domain_y)

        filename = os.path.join(output_dir, f"{prefix}_{i:04d}.in")
        escrever_in_gprmax(
            filename,
            materiais,
            blocos,
            domain_x=domain_x, domain_y=domain_y, domain_z=domain_z,
            dx_val=dx_val, dy_val=dy_val, dz_val=dz_val,
            time_window_s=time_window_s,
            title=f"{prefix}_{i:04d}",
        )

        labels.append({
            "filename": os.path.basename(filename),
            "esp_A":    espessuras[0],
            "esp_Bw":   espessuras[1],
            "materiais": {k: v for k, v in materiais.items()},
        })

    labels_file = os.path.join(output_dir, f"{prefix}_labels.json")
    with open(labels_file, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, ensure_ascii=False)

    print(f"Geradas {n_amostras} simulações em '{output_dir}'.")
    print(f"Labels salvos em '{labels_file}'.")
    return labels


if __name__ == "__main__":
    random.seed(42)
    gerar_dataset(
        n_amostras=10,
        output_dir="simulacoes_latossolo",
        prefix="latossolo",
        domain_x=1.0, domain_y=2.0, domain_z=1.0,
        dx_val=0.05, dy_val=0.05, dz_val=0.05,
        topo_solo=1.6,
        time_window_s=70e-9,
    )

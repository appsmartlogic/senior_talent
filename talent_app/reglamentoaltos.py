import zipfile
import shutil
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# ─────────────────────────────────────────────
# CONFIGURACIÓN
# ─────────────────────────────────────────────
TARIFAS = {
    "1": "$ 290.000",   # Mesa Completa
    "2": "$ 160.000",    # Media Mesa
}

DIAS = {
    "1": "Dia 13 de Mayo",
    "2": "Dia 14 de Mayo",
    "3": "Dia 0 de Mayo",
}

# Ruta al template Word
TEMPLATE_DOCX = Path(__file__).parent / "Reglamento_Agente_Atos_Bosque.docx"

# Carpeta de descargas del usuario
DOWNLOADS_DIR = Path.home() / "Downloads"
# ─────────────────────────────────────────────


def parse_input_block(texto: str) -> dict:
    patrones = {
        "nombre_completo":   r"Nombre completo\s*:\s*(.+)",
        "tipo_documento":    r"Tipo de documento.*?:\s*(.+)",
        "numero_documento":  r"N[úu]mero de documento\s*:\s*(.+)",
        "emprendimiento":    r"Nombre del emprendimiento\s*:\s*(.+)",
        "dias_raw":          r"D[íi]as de participaci[óo]n.*\):\s*(.+)",
        "autoriza_datos":    r"Autoriza tratamiento de datos.*?:\s*(.+)",
        "tipo_stand_raw":    r"Tipo de stand.*?:\s*(.+)",
    }
    resultado = {}
    for clave, patron in patrones.items():
        m = re.search(patron, texto, re.IGNORECASE)
        resultado[clave] = m.group(1).strip() if m else ""
    return resultado


def construir_variables(datos: dict) -> dict:
    dias_nums = [d.strip() for d in datos["dias_raw"].split(",") if d.strip()]
    dias_lista = [DIAS.get(d, f"Día {d}") for d in dias_nums]

    if len(dias_lista) > 1:
        dias_texto = " y ".join(dias_lista)
    elif dias_lista:
        dias_texto = dias_lista[0]
    else:
        dias_texto = ""

    num_dias = len(dias_nums)

    stand_key = datos["tipo_stand_raw"].strip()
    tarifa_base = TARIFAS.get(stand_key, "0")

    tarifa_num = int(re.sub(r"[^\d]", "", tarifa_base))
    tarifa_total = tarifa_num * num_dias
    tarifa_final = "$ {:,}".format(tarifa_total).replace(",", ".")

    if stand_key == "1":
        stand_nombre = "Stand 1 : Mesa de 2 Metros"
    elif stand_key == "2":
        stand_nombre = "Stand 2 : Mesa de 1 Metro"
    else:
        stand_nombre = stand_key

    print("DEBUG → dias_raw:", datos["dias_raw"])
    print("DEBUG → dias_nums:", dias_nums)
    print("DEBUG → dias_lista:", dias_lista)
    print("DEBUG → stand_key:", stand_key)
    print("DEBUG → tarifa_base:", tarifa_base)
    print("DEBUG → tarifa_num:", tarifa_num)
    print("DEBUG → num_dias:", num_dias)
    print("DEBUG → tarifa_total:", tarifa_total)

    hoy = datetime.now()
    meses = ["enero","febrero","marzo","abril","mayo","junio",
             "julio","agosto","septiembre","octubre","noviembre","diciembre"]
    fecha_firma = f"{hoy.day} de {meses[hoy.month-1]} de {hoy.year}"

    return {
        "{{NOMBRE_COMPLETO}}":    datos["nombre_completo"],
        "{{TIPO_DOCUMENTO}}":     datos["tipo_documento"].upper(),
        "{{NUMERO_DOCUMENTO}}":   datos["numero_documento"],
        "{{EMPRENDIMIENTO}}":     datos["emprendimiento"],
        "{{DIAS_PARTICIPACION}}": dias_texto,
        "{{AUTORIZA_DATOS}}":     datos["autoriza_datos"].upper(),
        "{{TIPO_STAND}}":         stand_nombre,
        "{{VALOR_TARIFA}}":       tarifa_final,
        "{{NOMBRE_FIRMA}}":       datos["nombre_completo"],
        "{{FECHA_FIRMA}}":        fecha_firma,
    }


def fill_docx(template_path: Path, variables: dict, output_path: Path):
    shutil.copy2(template_path, output_path)

    archivos = {}
    with zipfile.ZipFile(output_path, "r") as z:
        for name in z.namelist():
            archivos[name] = z.read(name)

    xml_targets = [n for n in archivos if n.startswith("word/") and n.endswith(".xml")]

    for name in xml_targets:
        contenido = archivos[name].decode("utf-8")
        for placeholder, valor in variables.items():
            contenido = contenido.replace(placeholder, valor)
        archivos[name] = contenido.encode("utf-8")

    with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in archivos.items():
            z.writestr(name, data)

    print(f"  ✔ DOCX generado: {output_path}")


def solicitar_datos_interactivo() -> str:
    print("\nPegue el bloque de datos y presione Enter dos veces:\n")
    lineas = []
    primera = input("> ").strip()
    lineas.append(primera)
    while True:
        linea = input()
        if linea == "":
            break
        lineas.append(linea)
    return "\n".join(lineas)


def main():
    if not TEMPLATE_DOCX.exists():
        print(f"❌ No se encontró el template Word: {TEMPLATE_DOCX}")
        sys.exit(1)

    texto = solicitar_datos_interactivo()
    datos = parse_input_block(texto)
    variables = construir_variables(datos)

    nombre_seguro = re.sub(r"[^\w\s-]", "", datos["emprendimiento"]).strip().replace(" ", "_")
    output_docx = DOWNLOADS_DIR / f"Reglamento_Atos_Bosque_{nombre_seguro}.docx"

    fill_docx(TEMPLATE_DOCX, variables, output_docx)

    print("\n✅ ¡Listo! Archivo generado en tu carpeta de Descargas:")
    print(f"   {output_docx}")


if __name__ == "__main__":
    main()
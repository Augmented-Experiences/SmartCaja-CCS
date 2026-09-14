/**
 * SmartCaja — Actualización del plugin
 *
 * Descarga la última versión del launcher/código con `git pull`.
 * Los datos del usuario (carpeta 'data/') están fuera de git y NO se tocan.
 * Generado con Gepeto (https://gepeto.pinokio.computer) y adaptado a SmartCaja.
 */
module.exports = {
  run: [
    {
      method: "log",
      params: {
        html: "<div style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;padding:12px 20px'><div style='display:flex;align-items:center;gap:8px;padding:10px 14px;background:#0f172a;border:1px solid #1e293b;border-radius:6px'><div style='width:8px;height:8px;border-radius:50%;background:#F4C10E;flex-shrink:0'></div><span style='color:#94a3b8;font-size:12px'>Actualizando SmartCaja a la última versión...</span></div></div>"
      }
    },
    {
      method: "shell.run",
      params: {
        message: "git pull"
      }
    },
    {
      method: "notify",
      params: {
        html: "SmartCaja actualizado. Si estaba en ejecución, reinícialo con Iniciar."
      }
    }
  ]
}

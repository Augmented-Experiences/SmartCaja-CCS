/**
 * SmartCaja — Configuración de Plugin Pinokio
 *
 * Menú dinámico según estado del plugin:
 *   - No instalado: botón de instalación
 *   - Instalado y corriendo: estado activo + botón detener + abrir UI
 *   - Actualizando / optimizando disco: estado de progreso
 *   - Instalado y detenido: iniciar + actualizar + ahorrar espacio + desinstalar
 */
module.exports = {
  title: "SmartCaja",
  description: "Herramienta de flujo de caja inteligente con IA local para PYMEs — Cámara de Comercio de Santiago (CCS)",
  icon: "icon.png",
  menu: async (kernel, info) => {
    // Verificar si el plugin está instalado (venv creado)
    var installed = await kernel.exists(__dirname, "venv")
    if (!installed) {
      return [
        {
          default: true,
          icon: "fa-solid fa-download",
          text: "Instalar",
          href: "install.json",
        },
      ]
    }
    // Estado de tareas de mantenimiento en curso
    var updating = await kernel.script.running(__dirname, "update.js")
    if (updating) {
      return [
        {
          default: true,
          icon: "fa-solid fa-rotate",
          text: "Actualizando",
          href: "update.js",
        },
      ]
    }
    var linking = await kernel.script.running(__dirname, "link.js")
    if (linking) {
      return [
        {
          default: true,
          icon: "fa-solid fa-file-zipper",
          text: "Optimizando disco",
          href: "link.js",
        },
      ]
    }
    // Verificar si el servidor está corriendo
    var running = await kernel.script.running(__dirname, "start.json")
    if (running) {
      return [
        {
          icon: "fa-solid fa-circle",
          text: "En ejecución",
          href: "start.json",
          style: "color: #00D53A",
        },
        {
          icon: "fa-solid fa-arrow-up-right-from-square",
          text: "Abrir UI",
          href: "http://127.0.0.1:{{port}}/ui/index.html",
        },
        {
          icon: "fa-solid fa-stop",
          text: "Detener",
          href: "stop.json",
        },
      ]
    }
    return [
      {
        default: true,
        icon: "fa-solid fa-play",
        text: "Iniciar",
        href: "start.json",
      },
      {
        icon: "fa-solid fa-rotate",
        text: "Actualizar",
        href: "update.js",
      },
      {
        icon: "fa-solid fa-file-zipper",
        text: "<div><strong>Ahorrar espacio en disco</strong><div>Deduplica librerías del entorno</div></div>",
        href: "link.js",
      },
      {
        icon: "fa-solid fa-trash",
        text: "Desinstalar",
        href: "reset.json",
      },
    ]
  },
}

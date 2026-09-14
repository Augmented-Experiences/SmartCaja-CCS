/**
 * SmartCaja — Ahorro de espacio en disco
 *
 * Deduplica las librerías del entorno virtual (carpeta 'venv') compartiéndolas
 * entre apps de Pinokio mediante enlaces, sin afectar el funcionamiento.
 * Generado con Gepeto (https://gepeto.pinokio.computer) y adaptado al venv 'venv'.
 */
module.exports = {
  run: [
    {
      method: "fs.link",
      params: {
        venv: "venv"
      }
    }
  ]
}

export default {
  async scheduled(controller, env, ctx) {
    ctx.waitUntil(
      fetch("https://asistencias-casaperu.onrender.com/api/demo/config", {
        method: "GET",
      }).catch(() => {})
    );
  },
};

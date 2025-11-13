import fp from "fastify-plugin";
import i18next from "i18next";
import Backend from "i18next-fs-backend";
import ICU from "i18next-icu";
import path from "path";

export default fp(async (fastify) => {
  await i18next.use(ICU).use(Backend).init({
    initImmediate: false,
    fallbackLng: "en",
    preload: ["en", "fr", "it", "es", "de", "ar"],
    backend: {
      loadPath: path.join(__dirname, "../locales/{{lng}}.json"),
    },
    interpolation: {
      escapeValue: false,
    },
  });

  fastify.decorate("t", (key: string, options?: any): string => {
    return String(i18next.t(key, options));
  });

  fastify.addHook("onRequest", (request, reply, done) => {
    const lang = request.cookies.lang || request.cookies.i18next || "en";
    i18next.changeLanguage(lang);
    request.t = (key: string, options?: any): string =>
      String(i18next.t(key, options));
    done();
  });
});

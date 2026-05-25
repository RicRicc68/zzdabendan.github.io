/**
 * Lightweight dev-only logger.
 * In production builds (NODE_ENV !== 'development') the functions are no-ops,
 * so no debug strings or arguments leak into the console.
 */
const isDev = process.env.NODE_ENV === "development";

export const devLog = isDev ? console.log.bind(console) : () => {};
export const devDebug = isDev ? console.debug.bind(console) : () => {};
export const devError = isDev ? console.error.bind(console) : () => {};

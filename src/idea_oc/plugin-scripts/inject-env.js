export const InjectEnvPlugin = async (ctx, options = {}) => {
  return {
    "shell.env": async (input, output) => {
      for (const [key, value] of Object.entries(options)) {
        output.env[key] = value
      }
    },
  }
}

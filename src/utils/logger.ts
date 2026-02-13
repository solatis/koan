const prefix = "[koan]";

export type Logger = <T extends Record<string, unknown> | undefined>(message: string, details?: T) => void;

export function createLogger(scope: string): Logger {
  const label = `${prefix} ${scope}`;
  return (message, details) => {
    if (details && Object.keys(details).length > 0) {
      console.log(`${label}: ${message}`, details);
    } else {
      console.log(`${label}: ${message}`);
    }
  };
}

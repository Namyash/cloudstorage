const text = new TextEncoder();
const decode = new TextDecoder('utf-8', { fatal: true });
export const overhead = 28;
const memoryLimit = 256 * 1024 ** 2;

export function randomBytes(size) {
  return crypto.getRandomValues(new Uint8Array(size));
}

export function base64(bytes) {
  return btoa(String.fromCharCode(...bytes));
}

export function fromBase64(value) {
  return Uint8Array.from(atob(value), char => char.charCodeAt(0));
}

async function deriveSecret(passphrase, salt) {
  if (!globalThis.crypto?.subtle) throw new Error('Open Family Drive using its HTTPS or localhost address.');
  const material = await crypto.subtle.importKey('raw', text.encode(passphrase), 'PBKDF2', false, ['deriveBits']);
  const params = { name: 'PBKDF2', hash: 'SHA-256', salt, iterations: 600000 };
  return new Uint8Array(await crypto.subtle.deriveBits(params, material, 256));
}

export function importVaultKey(secret) {
  return crypto.subtle.importKey('raw', secret, { name: 'AES-GCM' }, false, ['encrypt', 'decrypt']);
}

export async function recoverySettings(user, secret, passphrase, existingVerifier) {
  const salt = randomBytes(16);
  const recoverySecret = randomBytes(32);
  const passwordBits = await deriveSecret(passphrase, salt);
  const passwordKey = await importVaultKey(passwordBits);
  passwordBits.fill(0);
  const recoveryKey = await importVaultKey(recoverySecret);
  const code = 'FD1-' + base64(recoverySecret).replaceAll('+', '-').replaceAll('/', '_').replace(/=+$/, '');
  recoverySecret.fill(0);
  const verifier = existingVerifier || await sealText(await importVaultKey(secret), 'family-drive:v1', `${user}:vault`);
  return {
    code,
    settings: {
      salt: base64(salt),
      verifier,
      wrappedKey: base64(await seal(passwordKey, secret, `${user}:vault:passphrase`)),
      recoveryWrap: base64(await seal(recoveryKey, secret, `${user}:vault:recovery`)),
    },
  };
}

export async function unlockSecret(user, vault, input, recovery = false) {
  let secret;
  try {
    if (recovery) {
      const code = input.replace(/\s+/g, '');
      if (!vault.recoveryWrap || !/^FD1-[A-Za-z0-9_-]{43}$/.test(code)) throw new Error('Invalid recovery key.');
      const bits = fromBase64(code.slice(4).replaceAll('-', '+').replaceAll('_', '/') + '=');
      const key = await importVaultKey(bits);
      bits.fill(0);
      secret = await open(key, fromBase64(vault.recoveryWrap), `${user}:vault:recovery`);
    } else {
      const derived = await deriveSecret(input, fromBase64(vault.salt));
      if (vault.wrappedKey) {
        const key = await importVaultKey(derived);
        derived.fill(0);
        secret = await open(key, fromBase64(vault.wrappedKey), `${user}:vault:passphrase`);
      } else {
        secret = derived;
      }
    }
    const key = await importVaultKey(secret);
    if (await openText(key, vault.verifier, `${user}:vault`) !== 'family-drive:v1') throw new Error('Vault verification failed.');
    return { secret, key };
  } catch (error) {
    secret?.fill(0);
    if (!globalThis.crypto?.subtle) throw new Error('Open Family Drive using its HTTPS or localhost address.');
    throw new Error(recovery ? 'That recovery key could not unlock this vault.' : 'That vault passphrase is incorrect.');
  }
}

export async function seal(key, bytes, context) {
  const iv = randomBytes(12);
  const encrypted = await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: text.encode(context) }, key, bytes);
  const packet = new Uint8Array(iv.length + encrypted.byteLength);
  packet.set(iv);
  packet.set(new Uint8Array(encrypted), iv.length);
  return packet;
}

export async function open(key, packet, context) {
  if (packet.length < overhead) throw new Error('This encrypted file is incomplete.');
  const algorithm = { name: 'AES-GCM', iv: packet.subarray(0, 12), additionalData: text.encode(context) };
  return new Uint8Array(await crypto.subtle.decrypt(algorithm, key, packet.subarray(12)));
}

export async function sealText(key, value, context) {
  return base64(await seal(key, text.encode(value), context));
}

export async function openText(key, value, context) {
  return decode.decode(await open(key, fromBase64(value), context));
}

export function fileContext(user, file, part) {
  return `${user}:${file.id}:${part}:${file.size}`;
}

export async function downloadPrivate({ key, user, file, chunkSize, progress }) {
  let output;
  let reader;
  try {
    if (file.size > memoryLimit) {
      if (!window.showSaveFilePicker) throw new Error('Use Chrome or Edge on a computer to download private files larger than 256 MiB.');
      // Call the picker before a network wait to preserve the browser's user gesture.
      const handle = await window.showSaveFilePicker({ suggestedName: file.name });
      output = await handle.createWritable();
    }
    const response = await fetch(`/api/files/${file.id}/blob`);
    if (!response.ok || !response.body) throw new Error('Could not download this file. Check access and try again.');
    reader = response.body.getReader();
    const parts = [];
    let pending = new Uint8Array();
    let remaining = file.size;
    let index = 0;
    do {
      const plainLength = Math.min(remaining, chunkSize);
      const packet = new Uint8Array(plainLength + overhead);
      let filled = 0;
      while (filled < packet.length) {
        if (!pending.length) {
          const { value, done } = await reader.read();
          if (done) throw new Error('The download ended before the file was complete.');
          pending = value;
        }
        const count = Math.min(packet.length - filled, pending.length);
        packet.set(pending.subarray(0, count), filled);
        filled += count;
        pending = pending.subarray(count);
      }
      const bytes = await open(key, packet, fileContext(user, file, index));
      if (output) await output.write(bytes);
      else parts.push(bytes);
      remaining -= plainLength;
      index += 1;
      progress(file.size ? (file.size - remaining) / file.size : 1);
    } while (remaining > 0);
    if (pending.length || !(await reader.read()).done) throw new Error('The file has unexpected encrypted data.');
    if (output) {
      await output.close();
      output = null;
    } else {
      const url = URL.createObjectURL(new Blob(parts, { type: 'application/octet-stream' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = file.name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
  } catch (error) {
    if (output) await output.abort().catch(() => {});
    if (error.name === 'OperationError') throw new Error('The encrypted file could not be verified.');
    throw error;
  } finally {
    if (reader) await reader.cancel().catch(() => {});
  }
}

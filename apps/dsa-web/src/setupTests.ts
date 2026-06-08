import '@testing-library/jest-dom';

class MemoryStorageMock implements Storage {
  private readonly values = new Map<string, string>();

  get length() {
    return this.values.size;
  }

  clear() {
    this.values.clear();
  }

  getItem(key: string) {
    return this.values.get(key) ?? null;
  }

  key(index: number) {
    return Array.from(this.values.keys())[index] ?? null;
  }

  removeItem(key: string) {
    this.values.delete(key);
  }

  setItem(key: string, value: string) {
    this.values.set(key, String(value));
  }
}

class IntersectionObserverMock implements IntersectionObserver {
  readonly root = null;
  readonly rootMargin = '';
  readonly thresholds = [0];

  disconnect() {}

  observe() {}

  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }

  unobserve() {}
}

Object.defineProperty(globalThis, 'IntersectionObserver', {
  writable: true,
  value: IntersectionObserverMock,
});

const hasUsableLocalStorage = (() => {
  try {
    return (
      typeof globalThis.localStorage !== 'undefined'
      && typeof globalThis.localStorage.getItem === 'function'
      && typeof globalThis.localStorage.setItem === 'function'
      && typeof globalThis.localStorage.removeItem === 'function'
    );
  } catch {
    return false;
  }
})();

if (!hasUsableLocalStorage) {
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    value: new MemoryStorageMock(),
  });
}

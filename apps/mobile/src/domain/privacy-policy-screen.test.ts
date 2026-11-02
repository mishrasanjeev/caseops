import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import ts from "typescript";
import { createPrivacyPolicyOpener } from "./privacy-policy.ts";
const origin = "https://publisher.contract-fixture.org";
const projection = {
  url: origin + "/privacy-policy",
  version: "2026-10-28",
  sha256: "b".repeat(64),
};
function screen(
  input: unknown = projection,
  openUrl: (url: string) => Promise<unknown> = async () => undefined,
) {
  const cells: any[] = [],
    effects: { setup: () => () => void; cleanup?: () => void }[] = [],
    urls: string[] = [];
  let index = 0,
    disabled = false;
  const jsx = (type: any, props: any) => ({ type, props });
  const bindings: Record<string, any> = {
    react: {
      useRef: (value: any) => {
        const i = index++;
        return (cells[i] ||= { current: value });
      },
      useState: (initial: any) => {
        const i = index++;
        if (!(i in cells)) cells[i] = initial;
        return [
          cells[i],
          (v: any) => {
            cells[i] = typeof v === "function" ? v(cells[i]) : v;
          },
        ];
      },
      useEffect: (setup: () => () => void) => {
        const i = index++;
        if (!(i in cells)) {
          cells[i] = true;
          effects.push({ setup });
        }
      },
    },
    "react/jsx-runtime": { jsx, jsxs: jsx },
    "react-native": {
      View: "View",
      Text: "Text",
      Pressable: "Pressable",
      Linking: {
        openURL: (url: string) => {
          urls.push(url);
          return openUrl(url);
        },
      },
    },
    "expo-constants": {
      __esModule: true,
      default: {
        expoConfig: { extra: { privacyPolicy: input, webOrigin: origin } },
      },
    },
    "../domain/privacy-policy": { createPrivacyPolicyOpener },
    "./theme": { colors: { brand: "blue" }, styles: {} },
  };
  const code = ts.transpileModule(
    fs.readFileSync(
      new URL("../components/PrivacyPolicyLink.tsx", import.meta.url),
      "utf8",
    ),
    {
      compilerOptions: {
        module: ts.ModuleKind.CommonJS,
        target: ts.ScriptTarget.ES2022,
        jsx: ts.JsxEmit.ReactJSX,
      },
    },
  ).outputText;
  const module = { exports: {} as any };
  new Function("require", "module", "exports", code)(
    (name: string) => {
      assert.ok(Object.hasOwn(bindings, name), name);
      return bindings[name];
    },
    module,
    module.exports,
  );
  function render() {
    index = 0;
    const nodes: any[] = [];
    function visit(node: any) {
      if (Array.isArray(node)) node.forEach(visit);
      else if (node && typeof node === "object") {
        nodes.push(node);
        visit(node.props?.children);
      }
    }
    visit(module.exports.PrivacyPolicyLink({ disabled }));
    for (const effect of effects)
      if (!effect.cleanup) effect.cleanup = effect.setup();
    return nodes;
  }
  const initial = render();
  return {
    initial,
    render,
    urls,
    disabled: (value: boolean) => {
      disabled = value;
    },
    unmount: () => effects.forEach((x) => x.cleanup?.()),
    strictEffects: () =>
      effects.forEach((x) => {
        x.cleanup?.();
        x.cleanup = x.setup();
      }),
  };
}
const link = (nodes: any[]) =>
  nodes.find((x) => x.props?.testID === "privacy-policy-open");
const text = (nodes: any[]) =>
  nodes
    .filter((x) => x.type === "Text")
    .map((x) => x.props.children)
    .join(" ");
test("Account privacy link shows honest unconfigured state without a fabricated URL", () => {
  const s = screen(null);
  assert.equal(link(s.initial), undefined);
  assert.match(text(s.initial), /has not been configured/);
  assert.deepEqual(s.urls, []);
  s.unmount();
});
test("configured Account privacy link is labelled accessible and has a 48 point target", async () => {
  const s = screen();
  const target = link(s.initial);
  assert.equal(target.props.accessibilityRole, "link");
  assert.equal(target.props.accessibilityLabel, "Read privacy policy");
  assert.equal(target.props.style.minHeight, 48);
  target.props.onPress();
  await Promise.resolve();
  assert.deepEqual(s.urls, [projection.url]);
  s.unmount();
});
test("retained Account policy presses cannot launch twice before React renders", () => {
  const s = screen(projection, () => new Promise(() => {}));
  const press = link(s.initial).props.onPress;
  press();
  press();
  assert.equal(s.urls.length, 1);
  s.unmount();
});
test("Account policy unknown acknowledgement shows failure and removes the launch control", async () => {
  const s = screen(projection, async () => {
    throw Error("PRIVATE_SYNTHETIC");
  });
  link(s.initial).props.onPress();
  await Promise.resolve();
  await Promise.resolve();
  const nodes = s.render();
  assert.equal(link(nodes), undefined);
  assert.match(text(nodes), /Could not confirm/);
  assert.doesNotMatch(text(nodes), /PRIVATE_SYNTHETIC/);
  s.unmount();
});
test("retained Account policy callback is inert after unmount", () => {
  const s = screen();
  const press = link(s.initial).props.onPress;
  s.unmount();
  press();
  assert.deepEqual(s.urls, []);
});
test("Account policy strict effect retirement installs a fresh live controller", () => {
  const s = screen();
  s.strictEffects();
  link(s.render()).props.onPress();
  assert.deepEqual(s.urls, [projection.url]);
  s.unmount();
});

import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";
import ts from "typescript";
import { createPrivacyPolicyOpener } from "./privacy-policy.ts";
const origin = "https://publisher.contract-fixture.org";
// Identity tokens: the welcome must take its type from the shared theme.
const typeTokens = {
  title: { token: "title" },
  heading: { token: "heading" },
  body: { token: "body" },
  muted: { token: "muted" },
};
const projection = {
  url: origin + "/privacy-policy",
  version: "2026-10-28",
  sha256: "b".repeat(64),
};
function screen(
  input: unknown = projection,
  openUrl: (url: string) => Promise<unknown> = async () => undefined,
  welcome?: {
    onContinue: () => void;
    canOpen: () => boolean;
    isOpening?: () => boolean;
  },
) {
  const cells: any[] = [],
    effects: { setup: () => () => void; cleanup?: () => void }[] = [],
    urls: string[] = [];
  let index = 0,
    disabled = false;
  const observeOpen = (url: string) => {
    urls.push(url);
    return openUrl(url);
  };
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
      Image: "Image",
      StyleSheet: { create: (styles: unknown) => styles },
      View: "View",
      ScrollView: "ScrollView",
      Text: "Text",
      Pressable: "Pressable",
      Linking: { openURL: observeOpen },
    },
    "../../assets/app-icon.png": 1,
    "react-native-safe-area-context": { SafeAreaView: "SafeAreaView" },
    "./NativeControls": {
      NativeButton: "NativeButton",
      NativeProgress: "NativeProgress",
    },
    "expo-constants": {
      __esModule: true,
      default: {
        expoConfig: { extra: { privacyPolicy: input, webOrigin: origin } },
      },
    },
    "../domain/privacy-policy": { createPrivacyPolicyOpener },
    "./theme": {
      colors: { brand: "blue", danger: "red" },
      styles: { ...typeTokens, fill: {}, content: {}, divider: {} },
    },
  };
  function loadComponent(relative: string) {
    const code = ts.transpileModule(
      fs.readFileSync(new URL(relative, import.meta.url), "utf8"),
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
    return module.exports;
  }
  const policy = loadComponent("../components/PrivacyPolicyLink.tsx");
  bindings["./PrivacyPolicyLink"] = policy;
  bindings["./WelcomeFrame"] = loadComponent("../components/WelcomeFrame.tsx");
  const signIn = welcome
    ? loadComponent("../components/SignInPanel.tsx").SignInPanel
    : null;
  function render() {
    index = 0;
    const nodes: any[] = [];
    function visit(node: any) {
      if (Array.isArray(node)) node.forEach(visit);
      else if (node && typeof node === "object") {
        if (typeof node.type === "function") {
          visit(node.type(node.props));
        } else {
          nodes.push(node);
          visit(node.props?.children);
        }
      }
    }
    visit(
      welcome
        ? signIn({
            busy: disabled,
            error: null,
            onContinue: welcome.onContinue,
            canOpenBrowser: welcome.canOpen,
            privacyOpening: welcome.isOpening?.() ?? false,
            openPrivacyPolicy: observeOpen,
          })
        : policy.PrivacyPolicyLink({ disabled }),
    );
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

test("signed-out welcome keeps its sign-in action when no privacy policy is configured", (t) => {
  const s = screen(null, undefined, {
    onContinue: () => {},
    canOpen: () => true,
  });
  t.after(s.unmount);
  const mark = s.initial.find((node) => node.type === "Image");
  assert.equal(mark.props.source, 1);
  assert.equal(mark.props.accessible, false);
  const heading = s.initial.find(
    (node) => node.type === "Text" && node.props.accessibilityRole === "header",
  );
  assert.equal(heading.props.children, "Your legal workspace");
  assert.equal(heading.props.style, typeTokens.title);
  assert.match(text(s.initial), /matters, upcoming hearings and assigned work/);
  // House style: theme type tokens only, no ad-hoc face, caps or brand-coloured
  // copy on the welcome itself (the accent is reserved for the policy link).
  const texts = s.initial.filter((node) => node.type === "Text");
  const tokens = new Set<unknown>(Object.values(typeTokens));
  for (const node of texts) {
    const style = [node.props.style].flat();
    assert.ok(tokens.has(style[0]), JSON.stringify(node.props));
    for (const part of style) {
      assert.equal(part?.fontFamily, undefined);
      assert.equal(part?.fontSize, undefined);
      assert.equal(part?.textTransform, undefined);
      assert.notEqual(part?.color, "blue");
    }
  }
  assert.deepEqual(
    texts.map((node) => node.props.children),
    [
      "CaseOps",
      "Your legal workspace",
      "Find your matters, upcoming hearings and assigned work in one place.",
      "Sign in securely to continue.",
    ],
  );
  const signIn = s.initial.find((node) => node.props?.testID === "sign-in");
  assert.equal(signIn.props.label, "Continue to sign in");
  assert.equal(signIn.props.disabled, false);
  assert.equal(link(s.initial), undefined);
  assert.doesNotMatch(text(s.initial), /has not been configured/);
  assert.deepEqual(s.urls, []);
});

test("signed-out policy uses the approved URL and a retained press respects live sign-in admission", async (t) => {
  let loginInFlight = false;
  const s = screen(projection, undefined, {
    onContinue: () => {
      loginInFlight = true;
    },
    canOpen: () => !loginInFlight,
  });
  t.after(s.unmount);
  const target = link(s.initial);
  assert.equal(target.props.accessibilityRole, "link");
  assert.equal(target.props.style.minHeight, 48);
  const signIn = s.initial.find((node) => node.props?.testID === "sign-in");
  signIn.props.onPress();
  target.props.onPress();
  assert.deepEqual(s.urls, []);

  s.disabled(true);
  const duringSignIn = link(s.render());
  assert.equal(duringSignIn.props.accessibilityState.disabled, true);
  duringSignIn.props.onPress();
  assert.deepEqual(s.urls, []);

  loginInFlight = false;
  s.disabled(false);
  const ready = link(s.render());
  ready.props.onPress();
  ready.props.onPress();
  await Promise.resolve();
  assert.deepEqual(s.urls, [projection.url]);
});

test("a pending welcome privacy launch blocks retained sign-in presses until the browser acknowledges it", async (t) => {
  let privacyOpening = false;
  let signInCalls = 0;
  let acknowledge!: () => void;
  const opened = new Promise<void>((resolve) => {
    acknowledge = resolve;
  });
  const s = screen(
    projection,
    async () => {
      privacyOpening = true;
      try {
        await opened;
      } finally {
        privacyOpening = false;
      }
    },
    {
      onContinue: () => {
        signInCalls += 1;
      },
      canOpen: () => !privacyOpening,
      isOpening: () => privacyOpening,
    },
  );
  t.after(s.unmount);
  const signInButton = (nodes: any[]) =>
    nodes.find((node) => node.props?.testID === "sign-in");
  const retainedSignIn = signInButton(s.initial).props.onPress;
  const retainedPolicy = link(s.initial).props.onPress;
  retainedPolicy();
  retainedPolicy();
  retainedSignIn();
  assert.deepEqual(s.urls, [projection.url]);
  assert.equal(signInCalls, 0);
  assert.equal(signInButton(s.render()).props.disabled, true);

  acknowledge();
  await opened;
  await Promise.resolve();
  assert.equal(signInButton(s.render()).props.disabled, false);
  retainedSignIn();
  assert.equal(signInCalls, 1);
});

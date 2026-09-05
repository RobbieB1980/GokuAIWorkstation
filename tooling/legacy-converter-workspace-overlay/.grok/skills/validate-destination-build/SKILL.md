---
name: validate-destination-build
description: >-
  Run NeoForge 26.2 Gradle validation with destination JDK 25.
  Use when compiling, building, checking build/libs jars, or when ambient
  JAVA_HOME might be Java 8. Slash: /validate-destination-build.
---

# Validate with destination Java

## Command

```powershell
powershell -NoProfile -File C:\gokuai\projects\RB-Legacy-Java-Converter\tools\Build-WithDestinationJava.ps1 -ProjectRoot "<PROJECT>"
```

Optional narrower task:

```powershell
... -Tasks "compileJava --no-daemon --stacktrace"
```

## Checks

1. `org.gradle.java.home` in `gradle.properties` points at JDK 25+ (helper writes it).
2. Success for release bar: `build\libs\*.jar` exists (exclude sources/javadoc).
3. If log says `Gradle requires JVM 17+ ... JVM 8`, re-run the helper — do not treat as a mod source error.

## Reference

`C:\gokuai\Data\262r\converter\destination-java.md`

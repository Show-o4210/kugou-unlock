# Android v1.0 归档说明

- 版本：`versionCode 1` / `versionName 1.0`
- 归档日期：2026-09-28
- applicationId：`com.example.kugoudonwload`
- 最低版本：Android 8.0（API 26）
- 测试：10/10 JVM 单元测试通过；Android Lint 0 错误
- 网络权限：无 `INTERNET` 权限
- 本地候选 APK：`kugou-unlock-android-v1.0.0-debug.apk`
- APK SHA-256：`A961138AF661494E00A578A9885760E9758B3B6D6A2E46D14032465AA879DF74`

APK 是 Android 调试密钥签名的 debug 构建。源码归档不包含签名私钥、真实歌曲、真实密钥、
数据库、构建缓存或本机 SDK 路径。APK 二进制保存在被 Git 忽略的 `release-local/` 中，
后续可在获得远程写入授权后作为 GitHub Release 附件上传。

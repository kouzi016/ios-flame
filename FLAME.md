# ios-flame: ios-sweet の Pixel 4 (flame) 移植

[ios-sweet](https://github.com/dipa-studio/ios-sweet)（Redmi Note 10 Pro で iOS 16.7.16 を起動するプロジェクト）を Google Pixel 4（`flame`、Snapdragon 855 / SM8150）向けに移植したブランチです。

> **状態: 実機では未テストです。** Pixel 4 固有の値は Google 公開のカーネルソース（`android-msm-coral-4.14-android13`）と sm8150-mainline から取っています。実機の値で確認するまで、ここにある値はすべて推定です。初めて起動する前に必ず `tools/flame-check.py` を通してください。

## 何を変えたか

| 場所 | sweet | flame | 根拠 |
|---|---|---|---|
| フレームバッファ | 0x9c000000、1080×2400 | **0x9c400000、1080×2280** | `sm8150-floral-memory.dtsi` の cont_splash、mainline flame の simple-framebuffer |
| パネル | ビデオモード | **コマンドモード**（NT37280、DSC） | `dsi-panel-nt37280-dsc-fhd-cmd.dtsi` |
| 画面更新 | 不要 | shim がピンポンの autorefresh を確認し、止まっていれば有効化（`shim/mdp.c`） | `sde_hw_pingpong.c` |
| IMEM restart_reason | 0x146aa65c | **0x146bf65c** | `sm8150.dtsi` |
| カーネル用 RAM | 0x1_0000_0000 + 3.95 GiB | 同じ（**推定**）。shim が ABL の `/memory` で範囲を確認し、外れていれば起動しない | 6 GB 構成からの推定 |
| CPU | A55×6 + A76×2 | A55×4（0–3）+ A76×3 + A76 prime×1 | `sm8150.dtsi` |
| 音量+ | PM6150L GPIO2（SID 4） | **PM8150 GPIO6（SID 0）** | `sm8150-floral-common.dtsi` |
| 電源・音量− | PM6150 PON | PM8150 PON（同じアドレス） | `pm8150.dtsi` |
| タッチ | Goodix GT9896 / I²C SE7 | **ST FTM5 / SPI（QUPv3_0 SE4）**。ドライバ未実装のため止めてある | `sm8150-floral-touch.dtsi`、`fts_touch` |
| USB ログ | QUSB2 PHY | 既定で止めてある（SM8150 は SNPS femto PHY） | `sm8150-usb.dtsi` |
| boot.img | os_patch_level 2035-06 | **純正 boot.img と同じ値**（Keymaster 対策） | — |

sweet と同じまま使えるもの: GICv3（0x17a00000 / 0x17a60000）、UFS（0x1d84000）、PS_HOLD、SPMI アービター、タイマー PPI、RPMh。

カーネル側の変更は `xnu/patches/0082-flame-board.patch` の 1 枚だけです。sweet のパッチ 0001–0081 の上にそのまま当たることを確認済みです。

## 0. 前提

- **ブートローダーのアンロックが必須です。** ロックされた状態では `fastboot boot` が使えず、何も試せません。
  1. 設定 → デバイス情報 → ビルド番号を 7 回タップする
  2. 開発者向けオプション → **OEM ロック解除** をオンにする（グレーアウトしていればその端末はアンロックできません。キャリア版でよく起きます）
  3. `adb reboot bootloader` → `fastboot flashing unlock`（**端末は初期化されます**）
- macOS か Linux の PC、`adb` / `fastboot`、`dtc`（`brew install dtc android-platform-tools`）
- GitHub アカウント（カーネルは GitHub Actions の macOS ランナーでビルドします）
- iPhone X（iPhone10,3）iOS 16.7.16（20H392）の IPSW。各自が Apple から入手してください。このリポジトリには含めません。

## 1. 純正 boot.img と DTB（アンロック前でもできる）

Google の [Pixel 4 ファクトリーイメージ](https://developers.google.com/android/images#flame) の最終版を取得し、`image-flame-*.zip` に入っている `boot.img` を取り出します。

```sh
mkdir -p backup dtb
cp ~/Downloads/boot.img backup/boot.img
python3 tools/unpack_bootv2.py backup/boot.img dtb/boot_unpacked   # header.txt に os_version / patch level
```

戻すときはこのファクトリーイメージの `flash-all.sh` を使います。

## 2. 実機の値を吸い出して照合する

アンロック後に root の adb シェルを用意します。方法は Magisk、または flame 用 TWRP の `fastboot boot` です。

```sh
tools/flame-dump.sh                       # dumps/<日時>/ に live.dtb, iomem, GPT, persist などを保存
python3 tools/flame-check.py dumps/<日時>/live.dts
```

`MISMATCH` が 1 件でもあれば、該当する値を直してから先へ進んでください（`tools/mkadt.py`、`shim/console.h`・`mmu.h`・`shim.c`、`xnu/patches/0082`）。`dumps/` には IMEI と端末固有のキャリブレーションデータが入るので、git には入れず別の場所にも保管してください。

## 3. 段階的に起動する

一度にすべて試さず、次の順に進めます。各段階の結果は `NOTES.md` に書き残してください。

1. **shim だけ**（端末には何も書き込まない）

   ```sh
   shim/build.sh                 # payload なし → 診断モード
   fastboot boot shim/out/shim-boot.img
   ```

   赤い画面に `MDP AR pp0=... kicked=...`、続いて CPU、MMU、GIC、PSCI、UFS の診断が出れば成功です。
   - 画面が変わらない: autorefresh が効いていません。`MDP` 行の値を記録したうえで `mdp.c` を見直してください。
   - 即座に再起動する: アドレスの誤りです。

2. **カーネル、読み取り専用**: まだ userdata には書き込みません。

   ```sh
   gh workflow run xnu.yml -R YOU/ios-flame --ref flame
   gh run download RUN_ID -R YOU/ios-flame -n xnu-kernel -D xnu/out
   python3 tools/mkadt.py shim/out/flame.adt --highmem
   python3 tools/mkpayload.py xnu/out/kernel.development.sweet shim/out/flame.adt shim/out/payload.bin \
       --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 sweetkeys=0'
   shim/build.sh ../shim/out/payload.bin
   fastboot boot shim/out/shim-boot.img
   ```

   `kernel RAM not inside ABL /memory` と表示された場合は、その上に出る `DDR MiB` の行（ABL が報告した DDR の範囲）に収まるよう、`mkadt.py` の HIGH_* を直してください。カーネルのログが流れ、UFS が userdata を見つけたら成功です。
3. **iOS ルートを書き込む**: README の手順 2 と 4 で userdata に書き込み、`ufsrw=1 rootrw=1` を足して起動します。**その前に手順 2 の GPT バックアップがあるか必ず確認してください。** ios-topaz では UFS ドライバが LUN0 の GPT を壊した事例があります。
4. 起動できたら `sweetkeys=0` を外してボタンを試し、`cpus=4`（A55×4）に上げます。

## 未実装・次の作業

- **タッチ（FTM5 / SPI）**: 新しいドライバが必要です。必要な情報は揃っています。
  - SPI: SE4 0x890000、CS0、10 MHz
  - GPIO: IRQ TLMM 122、RST 127、**TLMM 126 を Low にしてバスを AP 側へ切り替える**
  - 電源: RPMh `ldoa14`（1.8 V）、`ldoa17`（3.0 V）
  - プロトコル: イベント読み出しは 0x87（先頭 1 バイトはダミー）、8 バイト/イベント、0x13 = down、0x23 = move、0x33 = up
  - 実装の参考: `kernel/msm-modules/fts_touch`

  タッチがないとロック画面の先へ進めないので、ここが最優先です。
- **シリアル**: SE12（0xa90000）の GENI UART が USB-C の SBU に出ている可能性があります（`fastboot oem uart enable`。未確認）。
- Wi-Fi、音声、セルラー、GPU は sweet / topaz と同じく未対応です。

## 注意

- 実験用です。普段使いの端末では試さないでください。userdata の内容はすべて失われます。
- iOS は Apple のソフトウェアです。IPSW、ルートイメージ、デバイスツリーのダンプは配布しないでください。

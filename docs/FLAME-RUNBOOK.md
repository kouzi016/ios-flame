# Pixel 4 (flame) で iOS 16.7.16 を SpringBoard まで起動させた手順

2026-10-21〜22 に実際に実行したコマンドの記録です。ここに書いたことは、すべてこの端末（Pixel 4 `flame`、SKU G020N、
TP1A.221005.002.B2）で動いた手順で、他の個体・他のファームウェアでの動作は未確認です。
最後に Android へ戻す方法と、ハマった点（症状 → 原因 → 対処）をまとめています。

> **userdata は消えます。** 手順 9 以降で Android のデータは失われます。ブートローダー、modem、persist などには触りません。
> `dumps/` と `backup/` には IMEI や校正データが入っています。git には入れないでください（`.gitignore` 済み）。

作業ディレクトリはリポジトリのルート（`ios-flame/`）です。

## 0. 必要なもの

| もの | 用途 | 入手 |
|---|---|---|
| Pixel 4（ブートローダーはアンロック済み） | 対象 | `fastboot flashing unlock`（端末は初期化される） |
| `adb`, `fastboot`, `dtc`, `gh`, `python3`, `lz4`, `mkbootimg`, `aarch64-linux-gnu-gcc` | ビルド | `brew install android-platform-tools dtc gh lz4 …` |
| GitHub アカウント | カーネルのビルド（macOS ランナー） | `gh auth login` |
| iPhone10,3 iOS 16.7.16 (20H392) の IPSW | ルートイメージの元 | Apple から各自で入手（このリポジトリには含めない） |
| Linux 環境（apfs-fuse, hfsprogs, hfsplus カーネルモジュール） | ルートイメージ作成 | 手順 7（lima の Ubuntu VM） |

## 1. 純正イメージのバックアップ（書き込み前）

```sh
# Google のファクトリーイメージ（flame 最終版）を backup/factory/ に置く。SHA-256 は公式ページの値と照合する
shasum -a 256 backup/factory/flame-tp1a.221005.002.b2-factory-38e4f49a.zip
# 純正 boot.img を取り出して DTB 等を展開（shim/build.sh が header.txt を読む）
python3 tools/unpack_bootv2.py backup/boot.img dtb/boot_unpacked
```

## 2. root を一時的に取る（Magisk、書き込みなし）

```sh
# Magisk v30.7 の APK（GitHub topjohnwu/Magisk の Releases、SHA-256 は GitHub の digest と一致を確認）
gh release download v30.7 -R topjohnwu/Magisk -p "Magisk-v30.7.apk" -D backup/magisk
adb install backup/magisk/Magisk-v30.7.apk
adb push backup/boot.img /sdcard/Download/boot_stock.img
# 端末の Magisk アプリで「インストール → ファイルを選択してパッチする」(boot_stock.img)
adb pull /sdcard/Download/magisk_patched-*.img backup/magisk/patched.img
adb reboot bootloader
fastboot boot backup/magisk/patched.img        # 一時起動。再起動すると root は消える
adb shell 'su -c id'                           # uid=0 を確認
```

## 3. 実機の値の吸い出しと照合

```sh
tools/flame-dump.sh        # dumps/<日時>/ に live.dtb, iomem, GPT, persist, modemst1/2 など（読み取りのみ）
```

`dtc` 1.8.1 が `live.dtb` で assertion failure を出したため、`fdtdump` の出力を `live.dts` として使った。

```sh
d=$(ls -dt dumps/* | head -1)
fdtdump $d/live.dtb > $d/live.dts
python3 tools/flame-check.py $d/live.dts
```

不一致は 1 件だった: カーネル用 RAM。実機の ABL `/memory` は `0x80000000+0x3cc00000`,
`0xc0000000+2G`, `0x140000000+3G` で、`0xc0000000`〜`0x1ffffffff` が連続した 4 GiB。
`tools/mkadt.py` の `HIGH_PHYS_BASE` を `0x100000000` → `0xc0000000` に変更済み（サイズは `0xfcc00000` のまま）。

## 4. シムをビルドして ABL に受け入れさせる

Pixel 4 の ABL は、次の条件を満たさないと `fastboot boot` を拒否する。`shim/build.sh` は 3 つとも自動で行う。

| 条件 | 満たさないときのエラー |
|---|---|
| カーネルは LZ4 の**フレーム形式**（`lz4 -9`。旧形式 `-l` と非圧縮は不可） | `Error verifying the received boot.img: Unsupported` |
| Image ヘッダーの `text_offset` が `0x80000`（`shim/start.S`） | `Invalid Parameter`（0 のとき） |
| 純正と同じ 64 MiB の AVB ハッシュフッター（署名なし）。`tools/avbtool.py`（AOSP android13-release） | 必須かどうかは未検証（付けたまま） |

```sh
shim/build.sh                   # payload なし = 診断モード。shim/out/shim-boot.img
fastboot boot shim/out/shim-boot.img
```

診断モードの成功: 赤い画面に `MDP AR pp0=… `、`DDR MiB …`、`UFS … GPT EFI PART` などが読める。
`MDP` のキックは既定でオフ（`shim/mdp.c`）。ABL は autorefresh を有効にしておらず（`pp0=pp1=0`）、
キックを入れると画面の半分がノイズになる。強制したいときは `EXTRA_CFLAGS=-DFLAME_MDP_KICK=1 shim/build.sh`。

## 5. カーネルのビルド（GitHub Actions）

```sh
git push -u origin flame
gh workflow run xnu.yml -R <あなた>/ios-flame --ref flame
gh run list -R <あなた>/ios-flame --workflow xnu.yml --limit 1      # run ID を確認（約 7 分）
gh run watch <run-id> -R <あなた>/ios-flame --exit-status
gh run download <run-id> -R <あなた>/ios-flame -n xnu-kernel -D xnu/out
cat xnu/out/SHA256SUMS && shasum -a 256 xnu/out/kernel.development.sweet
```

成果物（CI run 39620247252）: `xnu/out/kernel.development.sweet`、
SHA-256 `fcb9966b4a8e0d5d94a9fa8add8799740c635dd0b1a8b97e60779aee8187f7fd`。

## 6. ADT（デバイスツリー）と起動用イメージ

iPhone X の DeviceTree から `/product` ノードを取り出す（MobileGestalt が iOS のユーザーランドで必要とする）。

```sh
unzip -o -q "iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw" Firmware/all_flash/DeviceTree.d22ap.im4p -d /tmp/dt
python3 - <<'EOF'      # IM4P の中の LZFSE ペイロード（"bvx2" 以降）を切り出す
d=open('/tmp/dt/Firmware/all_flash/DeviceTree.d22ap.im4p','rb').read()
open('/tmp/dt/d22ap.lzfse','wb').write(d[d.find(b'bvx2'):])
EOF
mkdir -p research/ipsw-x
compression_tool -decode -a lzfse -i /tmp/dt/d22ap.lzfse -o research/ipsw-x/d22ap.adt
python3 tools/mkadt.py shim/out/flame.adt --highmem
```

読み取り専用でカーネルだけ起動して確認する場合（`ufsrw`/`rootrw` なし。userdata が Android のままなら
`unknown Volume Signature` でルートのマウントに失敗し続けるのが正常）:

```sh
python3 tools/mkpayload.py xnu/out/kernel.development.sweet shim/out/flame.adt shim/out/payload.bin \
  --cmdline 'debug=0xc serial=3 cpus=1 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin launchd_unsecure_cache=1 wdt=-1 sweetkeys=0'
shim/build.sh ../shim/out/payload.bin
fastboot boot shim/out/shim-boot.img
```

## 7. ルートイメージ作成用の Linux VM（lima）

Mac（Apple Silicon）に lima を入れ、専用の VM を作る（既存の VM には触らない）。

```sh
limactl start --name=ios-root --tty=false      # 既定テンプレート（Ubuntu 25.04 arm64, 4 CPU, 4 GiB, ディスク 100 GiB）
limactl shell ios-root -- bash -c '
  sudo apt-get update
  sudo apt-get install -y hfsprogs rsync android-sdk-libsparse-utils build-essential cmake git \
       libfuse3-dev libfuse-dev libbz2-dev zlib1g-dev libattr1-dev pkg-config python3 unzip lz4 sleuthkit
  # 既定のカーネルに hfsplus モジュールが無いので、新しいカーネルと extra モジュールを入れる
  sudo apt-get install -y linux-image-virtual linux-modules-extra-6.14.0-37-generic'
limactl stop ios-root && limactl start ios-root --tty=false     # 再起動して新しいカーネルへ
limactl shell ios-root -- bash -c 'sudo modprobe hfsplus fuse && lsmod | grep hfsplus'
# apfs-fuse（IPSW の APFS を読む。Ubuntu の公式パッケージは無い）。コミット 66b86bd で動作確認
limactl shell ios-root -- bash -c '
  mkdir -p ~/build && cd ~/build && git clone --recursive https://github.com/sgan81/apfs-fuse.git
  cd apfs-fuse && mkdir -p build && cd build && cmake .. -DCMAKE_BUILD_TYPE=Release && make -j4
  sudo cp apfs-fuse apfs-dump apfs-dump-quick /usr/local/bin/'
```

## 8. ルートイメージの作成

IPSW の OS / SystemOS / AppOS の DMG 名は `BuildManifest.plist` の `d22ap` のエントリで確認する。
この IPSW では `087-86698-044.dmg`（OS）、`087-86593-047.dmg`（SystemOS）、`087-86715-047.dmg`（AppOS）。

```sh
limactl shell ios-root -- bash -c '
  mkdir -p ~/work/dmg && cd ~/work/dmg &&
  unzip -o -q "/Users/<あなた>/Downloads/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw" \
        087-86698-044.dmg 087-86593-047.dmg 087-86715-047.dmg'
limactl shell ios-root -- bash -c '
  cd ~/work && /Users/<あなた>/…/ios-flame/tools/mkiosroot.sh \
     dmg/087-86698-044.dmg dmg/087-86593-047.dmg dmg/087-86715-047.dmg ios16-root.img 16G'   # 数分。fsck OK まで
limactl shell ios-root -- bash -c '
  cd ~/work && sudo fsck.hfsplus -fy ios16-root.img &&
  sudo mkdir -p /mnt/iosroot && sudo mount -t hfsplus -o loop,force ios16-root.img /mnt/iosroot &&
  sudo python3 /Users/<あなた>/…/ios-flame/tools/sweet-root-tweaks.py /mnt/iosroot &&
  sync && sudo umount /mnt/iosroot && sudo fsck.hfsplus -f -n ios16-root.img'
# スパース化: img2simg ではなく hfs-sparse.py を使う（理由は「ハマった点」の 1）。
# 実際の作業では、1 回目の全体書き込みは img2simg のイメージで行い、固まった末尾だけを
# `hfs-sparse.py ios16-root.img out.simg --start 3040000 --simg ios16-root.simg` で書き直した。
# 最初から hfs-sparse.py を使えば、書き直しは要らない（この形での全体書き込みは未実施）。
limactl copy tools/hfs-sparse.py ios-root:work/hfs-sparse.py
limactl shell ios-root -- bash -c 'cd ~/work && python3 hfs-sparse.py ios16-root.img ios16-root.simg'
limactl copy ios-root:work/ios16-root.simg backup/ios16-root.simg
shasum -a 256 backup/ios16-root.simg
```

`sweet-root-tweaks.py` は `mobileactivationd` のシステムコンテナが無い、という警告を出すが、起動には支障なかった。

## 9. userdata に書き込む（Android のデータが消える）

書き込み前の確認:

```sh
fastboot getvar product            # flame
fastboot getvar unlocked           # yes
fastboot getvar partition-size:userdata   # 0xC80FFB000（約 50 GiB）に 16 GiB のイメージが収まること
ls dumps/*/parts/gpt-sd?.bin backup/factory/*.zip        # GPT とファクトリーイメージのバックアップがあること
```

```sh
fastboot -S 128M flash userdata backup/ios16-root.simg 2>&1 | tee flash.log
```

- 進捗は、ログ最終行の文字列ではなく、`Sending sparse 'userdata' n/N` の**番号**で見る（`Writing 'userdata'` は毎回同じ行になる）。
- 途中で止めた場合・USB が切れた場合は、**必ず fastboot を入れ直して**（電源 10 秒長押し → 音量下を押しながら電源）、応答を確認してから書き直す。

## 10. iOS を起動する（毎回 fastboot から。書き込みなし）

```sh
python3 tools/mkpayload.py xnu/out/kernel.development.sweet shim/out/flame.adt shim/out/payload-ios.bin \
  --cmdline 'debug=0xc serial=3 cpus=4 keepsyms=1 -enable_kprintf_spam -noprogress rd=ufsroot0 unentitled_ios_sim_launch=1 ignition_level=1 wdt_test=no_user_checkin ufsrw=1 rootrw=1 launchd_unsecure_cache=1 wdt=-1 sweetkeys=0 sweetfb_noconsole=1 sweetfb_hz=30'
shim/build.sh ../shim/out/payload-ios.bin
fastboot boot shim/out/shim-boot.img
```

| 引数 | 意味 |
|---|---|
| `cpus=4` | A55×4 を起動（`cpus=1` だと launchd が約 80 秒、`cpus=4` で約 56 秒） |
| `ufsrw=1 rootrw=1` | userdata を書き込み可能で、ルートとしてマウント |
| `sweetkeys=0` | ボタンのドライバを止める（flame の GPIO 割り当ては未検証） |
| `sweetfb_noconsole=1 sweetfb_hz=30` | カーネルの文字を GUI の上に描かない／パネルの更新周期。**flame では効果を未確認** |

ログを画面で見たいときは `sweetfb_noconsole=1 sweetfb_hz=30` を外す（キーバグ、launchd、SpringBoard のスタックが流れる）。

## 11. Android に戻す

```sh
# 純正ファクトリーイメージ（backup/factory/）を展開して、同梱の flash-all.sh を使う。
# userdata を含めて全部書き直す。未検証（この手順では戻していない）。
```

userdata 以外のパーティションは、この作業のあいだ一度も書き込んでいない。

## ハマった点（症状 → 原因 → 対処）

| 症状 | 原因 | 対処 |
|---|---|---|
| 1. `fastboot flash userdata` が最後のチャンクで 15 分以上「固まる」。途中で止めると末尾が未書き込みになり、`keybagd` が `FATAL KEYBAG ERROR: kb_load` を繰り返す（ファイルは見えるが中身がゼロ） | `img2simg` は、ゼロのブロックを FILL にする。Pixel 4 のブートローダーは、これを**実際にゼロで書き込む**。末尾の約 4.3 GiB の空き領域が最後のピースに入り、12 分以上かかっていた | `tools/hfs-sparse.py` で、HFS+ の割り当てビットマップから未使用ブロックを DONT_CARE にする。末尾の 70 MB は 9 秒で書けた |
| 2. `fastboot boot` が `Unsupported` で拒否される | カーネルが非圧縮／旧形式の LZ4 | LZ4 フレーム形式（`lz4 -9`） |
| 3. `fastboot boot` が `Invalid Parameter` で拒否される | Image ヘッダーの `text_offset` が 0 | `0x80000` |
| 4. 画面の半分がノイズになる | `shim/mdp.c` の autorefresh のキック | 既定でオフ |
| 5. `flame-check` が RAM の不一致を報告 | 推定値 `0x100000000` が実機の DDR の外 | `HIGH_PHYS_BASE = 0xc0000000` |
| 6. `usb_read failed … No such process`、`fastboot devices` から端末が消える | USB の瞬断（ケーブル／端子） | 端末を fastboot に入れ直し、応答を数回確認してから再開 |
| 7. 「固まった」と判断する監視が誤検知する | ログ最終行の文字列を比べていた（毎回 `Writing 'userdata'`） | チャンク番号 `n/N` の増加で判定する |
| 8. `dtc` が `live.dtb` で abort する | dtc 1.8.1 の `propval_cell` assertion | `fdtdump` の出力を `live.dts` として使う（`flame-check.py` は読める） |
| 9. `limactl create … template:ubuntu-24.04` が失敗する | lima 1.2.1 のテンプレート指定の書式 | `limactl start --name=ios-root` で既定テンプレートを使った |

## 現在の状態（2026-10-22）

- **確認済み:** XNU が実機で起動する／UFS の読み書き／ルート（HFS+）のマウント／launchd、keybagd、backboardd、SpringBoard の起動（カーネルのスタックサンプラーの出力で確認）／`cpus=4`。
- **未確認:** GUI（ロック画面）が画面に出るか／ボタン（`sweetkeys=0` を外した場合）／Android への復旧手順。
- **未実装:** タッチ（ST FTM5、SPI。FLAME.md 参照）、Wi-Fi、Bluetooth、音声、セルラー、GPU。

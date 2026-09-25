# 🧠 Capsule Python API 

Данная обёртка предоставляет высокоуровневый интерфейс для взаимодействия с Capsule API средствами языка Python.  
Она позволяет подключиться к одному из списка поддерживаемых девайсов, собирать данные EEG, PPG, MEMS и произведенные от них метрики с последующим сохранением в `.npy` формате.

---

## ⚙️ Основные возможности, представленные в примере

### 🔍 Поиск и подключение устройств
  Поиск доступных устройств с выводом серийного номера, версии прошивки и типа.
  
  Список поддерживаемых устройств указан в `DeviceType.py`:
  - Band
  - Buds
  - Headphones
  - Impulse
  - Any
  - BrainBit
  - SinWave (сгенерированный сигнал с пиками на фиксированных частотах)
  - Noise (сгенерированный сигнал равномерного шума)

### ⚡ Получение данных в реальном времени  
  Поддерживаются следующие данные:
  - EEG (сырые и фильтрованные)
  - PSD (Power Spectral Density)
  - Сопротивления электродов (импеданс)
  - Заряд аккумулятора
  - MEMS (акселерометр и гироскоп)
  - PPG (фотоплетизмограмма)
  - Эмоции (стресс, фокус, самоконтроль)
  - Кардиометрики (ЧСС, индекс напряжения, артефакты, SDNN и т.д.)
  - Метрики Productivity (расслабление, концентрация, усталость, обратная усталость и т.д.)
  - Физиологические состояния (усталость, концентрация, расслабленность, вовлеченность, стресс)
  - **FusionCognitive v2** (когнитивная нагрузка 0–100, мультимодальная fusion-метрика) — см. `FUSION_COGNITIVE.md`

  Для получения **любых** из вышеперечисленных данных необходимо создать соответствующий колбэк и регулярно вызывать `device_locator.update()`. Ниже приведён пример получения уровня заряда батареи:
  ```python
    def on_battery_charge(device: Device, charge: int):
        print("Device battery: {b}".format(b = charge))

    device.set_on_battery_charge_changed(on_battery_charge)
    # device_locator.update() вызывается внутри non_blocking_cond_wait.
    non_blocking_cond_wait(EventFiredState(), event_name='just wait', total_sleep_time=60)
  ``` 
  
  Часть данных может быть недоступна в зависимости от выбранного устройства. Например, при выборе `DeviceType.SinWave` или `DeviceType.Noise` недоступны MEMS и PPG.

### 💾 Сохранение данных
В экзампле реализовано поточное сохранение данных в файлы `.npy`.  
Данные, которые обновляются очень часто (такие как EEG и MEMS) перед записью в файл предварительно сохраняются в буферы, которые наполняются до определенного лимита и дополняют файл.

>  ⚠️ Важно
>
> - `.npy` файлы предназначены для короткой записи. Для длительных записей лучше использовать более подходящие для этого форматы, например HDF5. В большей степени касается `psd.npy`, поскольку он очень быстро заполняет память и может значительно снизить производительность. Общее правило - в колбеках нежелательно выполнять затратные по времени операции (вычисления или I/O).
> - При повторном запуске `main.py` файлы `.npy` не будут очищены, а продолжат дополняться новыми данными. Это важно учитывать при выполнении действий, изменяющих shape массивов, хранящихся в файлах (такое может случиться при смене биполярного режима на монополярный).

## 🧠 Калибровки
Для получения многих метрик необходимы пройденные калибровка с закрытыми глазами и калибровки бейслайнов.

Таблица необходимости калибровок:

|  | Works without closed-eyes calibration?  | Works without Productivity baseline calibration?  | Works without Physiological States baseline calibration? |
| ------------- | ------------- | ------------- | ------------- |
| **EEG**  | YES  | YES  | YES |
| **PPG**  | YES  | YES  | YES |
| **MEMS**  | YES  | YES  | YES |
| **Emotions**  | YES | YES | YES |
| **Productivity**  | NO  | NO | YES |
| **Physiological States**  | NO  | NO  | NO |
| **Power Spectral Density** | YES | YES | YES |
| **Battery charge** | YES | YES | YES |
| **Resistances** | YES | YES | YES |
| **Cardio** | YES | YES | YES |

Всего есть три вида калибровок (указаны в порядке прохождения):
1. Калибровка с закрытыми глазами. Нужна для получения IndividualNFBData. Есть два варианта её прохождения -- быстрая и долгая. В долгой калибровке дважды чередуются этапы закрытых и открытых глаз. `Calibrator.calibrate()`.
![alt text](individual_nfb_calibration.png)
Быстрая калибровка состоит только из одного этапа - закрытые глаза в течении 30 секунд. `Calibrator.calibrate_quick()`.
2. Калибровка Productivity бейслайнов `Productivity.calibrate_baselines()`. В течение этой калибровки собираются базовые значения метрик Productivity, которые нужны для того, чтобы понять, как изменяется состояние пользователя в течение сессии относительно её начала. Например, если concentration на момент начала был 1.2, а спустя 15 минут стал 4, это может сигнализировать о повышении концентрации и фокуса. Необходима для работы классификаторов Productivity и Physiological States.
3. Калибровка `PhysiologicalStates.calibrate_baselines()` нужна для работы классификатора Physiological States.  


В качестве альтернативы повторному прохождению калибровок можно использовать импорт значений.

1. 
    ```python
    individual_nfb_data = IndividualNFBData(timestamp_milli=1,
                                            individual_frequency=10,
                                            individual_peak_frequency=10,
                                            individual_peak_frequency_power=10,
                                            individual_peak_frequency_suppression=2,
                                            individual_bandwidth=6,
                                            individual_normalized_power=6,
                                            lower_frequency=7,
                                            upper_frequency=13)
    calibrator.import_alpha(individual_nfb_data=individual_nfb_data)
    ```

2. 
    ```python
    productivity_baselines = Productivity_Baselines(concentration=0.4303644895553589,
                                                    fatigue=3.231703281402588,
                                                    gravity=0.6188167333602905,
                                                    productivity=0.6188167333602905,
                                                    relax=2.3246757984161377,
                                                    reverse_fatigue=0.3094368875026703, 
                                                    timestamp=0)
    prod.import_baselines(productivity_baselines)
    ```

3. 
    ```python
    phy_baselines = PhysiologicalStates_Baselines(timestamp_milli=0,
                                                    alpha=0.2845260500907898,
                                                    beta=0.5158727169036865,
                                                    alpha_gravity=4.821654319763184,
                                                    beta_gravity=0.13223537802696228,
                                                    concentration=1.837107539176941)
    phy.import_baselines(baselines=phy_baselines)
    ```


## 🔌 Пайплайн подключения и сбора данных
1. Подключаем библиотеку `CapsuleClient.dll` (win) или `libCapsuleClient.dylib` (macOS).
2. Создаём DeviceLocator — объект поиска устройств
3. Подписываемся на колбэк получения списка устройств
4. Начинаем поиск устройств определённого типа (Band, Headphones, BrainBit, Noise) в цикле
5. После нахождения устройства создаём объект Device, ассоциированный с ним.
6. Подписываемся на получение данных (Battery, EEG, PSD, PPG, MEMS, Productivity и т.д.). Обязательно до `Device.start()`.
7. Подключаемся к устройству (в биполярном или монополярном режиме)
8. Запускаем получение данных от устройства `Device.start()`
9. Создаём объект Calibrator и проходим калибровки с закрытыми глазами (или импортируем)
10. После калибровки начинается сбор бейслайнов (обязателен для получения многих метрик)
11. После этого данные начинают выдаваться в колбэках и сохраняются в `.npy` файлы

>  ⚠️ Важно
>
> Все необходимые вам классификаторы должны быть созданы **ДО** команды `device.start()`
---


## 🔄 Монополярный и биполярный режим

При подключении устройства через метод `device.connect(bipolarChannels=True/False)` можно выбрать режим записи данных:

* **Монополярный режим** (`bipolarChannels=False`):
  В этом режиме данные снимаются с каждого канала отдельно относительно общего референтного электрода.
  Это позволяет получать абсолютные значения потенциалов с каждой точки измерения. Например, доступны сырые данные EEG и PSD для каждого канала по отдельности.

* **Биполярный режим** (`bipolarChannels=True`):
  В этом режиме сигнал получается как разность потенциалов между парой электродов — то есть один канал вычитается из другого.
  Такой способ помогает уменьшить влияние артефактов, таких как моргания. Это особенно актуально для Brainbit и Band, поскольку у них референт располагается на Fpz.
  Биполярные отведения формируются по следующему принципу: количество каналов уменьшается вдвое при четном количестве. При нечётном количестве каналов самый правый остаётся монополярным, а их количество становится N/2+1
  `Ch0`, `Ch1`, `Ch2`, `Ch3`, `Ch4`, `Ch5`, `Ch6` → `Ch0-Ch1`, `Ch2-Ch3`, `Ch4-Ch5`, `Ch6`.

Соответственно, изменяется и количество возвращаемых каналов у объектов `EEGTimedData` и `PSDData`.
  




## 🖥️ GUI test app (metrics viewer)

English quick start for `capsule_metrics_gui.py`:

1. Copy `CapsuleClient.dll` into `CapsuleClientPython` (same folder as the script).
2. `pip install` is not required (uses built-in `tkinter`).
3. Run:
   ```powershell
   cd path\to\CapsuleClientPython
   python capsule_metrics_gui.py
   ```
4. Workflow: **Load library** → **Scan devices** → pick device → **Connect** → **Start stream** → run calibrations (closed-eyes, then Productivity, Physiological, FusionCognitive if DLL supports v2).
5. Watch **Live metrics** update; adjust Fusion weights and click **Apply weights** after Fusion module is created.

Without a FusionCognitive-enabled DLL, existing metrics (Emotions, Productivity, Physiological States, Cardio) still work; Fusion rows show "DLL has no v2 API".

---

## 🚀 Быстрый старт

> Сперва убедитесь, что у вас:
> - Установлен Python 3.11+
> - Есть `CapsuleClient.dll` (win) или `libCapsuleClient.dylib` (macOS)
> - Подключено устройство по Bluetooth

1. Откройте `main.py` в режиме редактирования и установите нужный вам `DeviceType`, например `DeviceType.Band`.
2. Запустите консоль или PowerShell и перейдите в директорию где расположен `main.py`:
    ```powershell
    cd C:\EXAMPLE\USER\PATH\TO\capsule\Wrappers\python\CapsuleClientPython
    ```
3. Поместите `CapsuleClient.dll` (win) или `libCapsuleClient.dylib` (macOS) в директорию с `main.py`.
4. Установите необходимые зависимости:
    ```powershell
    pip install numpy
    ```
5. Запусите экзампл:
    ```powershell
    python main.py
    ```
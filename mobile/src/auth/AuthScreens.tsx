import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  type LayoutChangeEvent,
  Modal,
  Pressable,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";

import { styles } from "../styles/appStyles";
import type { City } from "../types";
import {
  formatOtpCountdown,
  isPhoneReady,
  normalizePhoneForApi,
  sanitizePhoneInput,
} from "./authUtils";

type AuthStep = "landing" | "request" | "confirm";
type AuthIntent = "login" | "signup";

const landingSlides = [
  {
    key: "no-deposit",
    title: "Аренда без залога!",
    subtitle: "Берите нужное без лишних трат и замороженных денег.",
    illustration: "no-deposit" as const,
  },
  {
    key: "nearby",
    title: "Постаматы рядом",
    subtitle: "Выберите ближайшую точку и заберите товар по пути домой.",
    illustration: "nearby" as const,
  },
  {
    key: "fast",
    title: "Быстрое бронирование",
    subtitle: "Номер телефона, пара шагов и бронь уже ждёт вас в постамате.",
    illustration: "fast" as const,
  },
  {
    key: "return",
    title: "Простой возврат",
    subtitle: "Верните товар обратно в ячейку и закройте аренду за минуту.",
    illustration: "return" as const,
  },
];

export function AuthScreen({
  authStep,
  authIntent,
  phone,
  smsCode,
  devCode,
  authMessage,
  authError,
  authLoading,
  codeTtlSeconds,
  onPhoneChange,
  onCodeChange,
  onRequestCode,
  onConfirmCode,
  onResendCode,
  onBack,
  onDemo,
  onStartLogin,
  onStartRegistration,
}: {
  authStep: AuthStep;
  authIntent: AuthIntent;
  phone: string;
  smsCode: string;
  devCode: string;
  authMessage: string;
  authError: string;
  authLoading: boolean;
  codeTtlSeconds: number;
  onPhoneChange: (value: string) => void;
  onCodeChange: (value: string) => void;
  onRequestCode: () => void;
  onConfirmCode: () => void;
  onResendCode: () => void;
  onBack: () => void;
  onDemo: () => void;
  onStartLogin: () => void;
  onStartRegistration: () => void;
}) {
  const codeInputRef = useRef<TextInput | null>(null);
  const lastAutoSubmittedCodeRef = useRef("");
  const welcomeScrollRef = useRef<ScrollView | null>(null);
  const welcomeScrollX = useRef(new Animated.Value(0)).current;
  const [privacyPolicyVisible, setPrivacyPolicyVisible] = useState(false);
  const codeDigits = Array.from({ length: 4 }, (_, index) => smsCode[index] ?? "");
  const isSignup = authIntent === "signup";
  const isPhoneValid = isPhoneReady(phone);
  const isCodeReady = smsCode.trim().length === 4;
  const canResendCode = codeTtlSeconds <= 0 && !authLoading;
  const normalizedPhone = normalizePhoneForApi(phone);
  const [carouselWidth, setCarouselWidth] = useState(0);
  const slideWidth = carouselWidth || 320;
  const dotSize = 10;
  const dotGap = 10;
  const dotStep = dotSize + dotGap;
  const indicatorFrames = useMemo(
    () =>
      landingSlides.reduce<{
        inputRange: number[];
        translateRange: number[];
        widthRange: number[];
      }>(
        (acc, _, index) => {
          const slideOffset = index * slideWidth;
          acc.inputRange.push(slideOffset);
          acc.translateRange.push(index * dotStep);
          acc.widthRange.push(dotSize);

          if (index < landingSlides.length - 1) {
            acc.inputRange.push(slideOffset + slideWidth / 2);
            acc.translateRange.push(index * dotStep);
            acc.widthRange.push(dotSize + dotStep);
          }

          return acc;
        },
        { inputRange: [], translateRange: [], widthRange: [] },
      ),
    [dotSize, dotStep, slideWidth],
  );
  const activeDotTranslateX = welcomeScrollX.interpolate({
    inputRange: indicatorFrames.inputRange,
    outputRange: indicatorFrames.translateRange,
    extrapolate: "clamp",
  });
  const activeDotWidth = welcomeScrollX.interpolate({
    inputRange: indicatorFrames.inputRange,
    outputRange: indicatorFrames.widthRange,
    extrapolate: "clamp",
  });

  function handleWelcomeLayout(event: LayoutChangeEvent) {
    const width = event.nativeEvent.layout.width;
    if (width > 0 && width !== carouselWidth) {
      setCarouselWidth(width);
    }
  }

  useEffect(() => {
    if (smsCode.trim().length < 4) {
      lastAutoSubmittedCodeRef.current = "";
      return;
    }

    if (authLoading || lastAutoSubmittedCodeRef.current === smsCode.trim()) {
      return;
    }

    lastAutoSubmittedCodeRef.current = smsCode.trim();
    onConfirmCode();
  }, [authLoading, onConfirmCode, smsCode]);

  if (authStep === "landing") {
    return (
      <ScrollView
        contentContainerStyle={styles.welcomeShell}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        <View style={styles.welcomeTopBlock}>
          <Animated.ScrollView
            ref={welcomeScrollRef}
            horizontal
            pagingEnabled
            decelerationRate="fast"
            bounces={false}
            directionalLockEnabled
            showsHorizontalScrollIndicator={false}
            contentContainerStyle={styles.welcomeCarouselContent}
            style={styles.welcomeCarousel}
            onLayout={handleWelcomeLayout}
            onScroll={Animated.event(
              [{ nativeEvent: { contentOffset: { x: welcomeScrollX } } }],
              { useNativeDriver: false },
            )}
            scrollEventThrottle={16}
          >
            {landingSlides.map((slide) => (
              <View key={slide.key} style={[styles.welcomeSlide, { width: slideWidth }]}>
                <View style={styles.welcomeIllustrationWrap}>
                  <WelcomeSlideIllustration kind={slide.illustration} />
                </View>
                <Text style={styles.welcomeTitle}>{slide.title}</Text>
                <Text style={styles.welcomeSubtitle}>{slide.subtitle}</Text>
              </View>
            ))}
          </Animated.ScrollView>

          <View style={styles.welcomeDotsRow}>
            {landingSlides.map((slide, index) => (
              <Pressable
                key={slide.key}
                onPress={() => {
                  welcomeScrollRef.current?.scrollTo({ x: slideWidth * index, animated: true });
                }}
              >
                <View style={styles.welcomeDot} />
              </Pressable>
            ))}
            <Animated.View
              pointerEvents="none"
              style={[
                styles.welcomeDotActive,
                {
                  width: activeDotWidth,
                  transform: [{ translateX: activeDotTranslateX }],
                },
              ]}
            />
          </View>

          <Pressable onPress={onDemo} style={styles.welcomeLinkWrap}>
            <Text style={styles.welcomeLink}>Посмотреть каталог</Text>
          </Pressable>
        </View>

        <View style={styles.welcomeButtonsBlock}>
          <Pressable style={styles.welcomePrimaryButton} onPress={onStartLogin}>
            <Text style={styles.welcomePrimaryButtonText}>Войти</Text>
          </Pressable>
          <Pressable style={styles.welcomeSecondaryButton} onPress={onStartRegistration}>
            <Text style={styles.welcomeSecondaryButtonText}>Зарегистрироваться</Text>
          </Pressable>
        </View>
      </ScrollView>
    );
  }

  return (
    <>
      <ScrollView
        contentContainerStyle={authStep === "confirm" ? styles.entryConfirmShell : styles.entryShell}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {authStep === "request" ? (
          <>
            <View style={styles.entryCenteredArea}>
              <View style={styles.entryTitleBlock}>
                <Text style={styles.entryTitle}>{isSignup ? "Регистрация" : "Вход"}</Text>
                <Text style={styles.entrySubtitle}>
                  {isSignup ? "Добро пожаловать" : "Введите номер РФ или РБ"}
                </Text>
              </View>

              <View style={styles.softInputShell}>
                <View style={styles.softInputIconWrap}>
                  <PhoneGlyph />
                </View>
                <TextInput
                  value={phone}
                  onChangeText={(value) => onPhoneChange(sanitizePhoneInput(value))}
                  style={styles.softInputText}
                  placeholder="+79991234567"
                  placeholderTextColor="#d1d3db"
                  keyboardType="phone-pad"
                  autoCapitalize="none"
                  autoCorrect={false}
                  autoComplete="tel"
                />
              </View>

              <Text style={styles.entrySupportText}>РФ можно вводить без `+7`. Номера РБ вводите только через `+375`.</Text>

              <Pressable
                style={[
                  styles.softPrimaryButton,
                  (!isPhoneValid || authLoading) && styles.softPrimaryButtonDisabled,
                ]}
                onPress={onRequestCode}
                disabled={!isPhoneValid || authLoading}
              >
                <Text style={styles.softPrimaryButtonText}>
                  {authLoading ? "Отправляем..." : "Далее"}
                </Text>
              </Pressable>

              <View style={styles.entrySwitchBlock}>
                <Text style={styles.entrySwitchText}>{isSignup ? "Есть аккаунт?" : "Нет аккаунта?"}</Text>
                <Pressable onPress={isSignup ? onStartLogin : onStartRegistration}>
                  <Text style={styles.entrySwitchLink}>{isSignup ? "Войти" : "Зарегистрироваться"}</Text>
                </Pressable>
              </View>

              <Pressable style={styles.entryBackButton} onPress={onBack}>
                <Text style={styles.entryBackButtonText}>Назад</Text>
              </Pressable>
              {authError ? <Text style={styles.entryErrorText}>{authError}</Text> : null}
            </View>

            <Text style={styles.entryLegalText}>
              Выполняя вход, я подтверждаю, что прочитал{" "}
              <Text style={styles.entryLegalLink} onPress={() => setPrivacyPolicyVisible(true)}>
                Политику конфиденциальности
              </Text>
            </Text>
          </>
        ) : (
          <View style={styles.entryConfirmScreen}>
            <Pressable style={styles.entryIconBackButton} onPress={onBack}>
              <Text style={styles.entryIconBackText}>←</Text>
            </Pressable>

            <View style={styles.entryConfirmBody}>
              <View style={styles.entryConfirmTitleBlock}>
                <Text style={styles.entryTitle}>Код подтверждения</Text>
                <Text style={styles.entrySubtitle}>
                  На номер <Text style={styles.entrySubtitleStrong}>{normalizedPhone || phone}</Text> отправлен код
                  {"\n"}для подтверждения входа
                </Text>
              </View>

              <Pressable style={styles.entryOtpRow} onPress={() => codeInputRef.current?.focus()}>
                {codeDigits.map((digit, index) => (
                  <View
                    key={`${index}-${digit || "empty"}`}
                    style={[
                      styles.entryOtpBox,
                      digit && styles.entryOtpBoxFilled,
                      !digit && smsCode.length === index && styles.entryOtpBoxActive,
                    ]}
                  >
                    <Text style={styles.entryOtpBoxText}>{digit || ""}</Text>
                  </View>
                ))}
              </Pressable>

              <TextInput
                ref={codeInputRef}
                value={smsCode}
                onChangeText={(value) => onCodeChange(value.replace(/[^0-9]/g, "").slice(0, 4))}
                style={styles.hiddenOtpInput}
                placeholder="1234"
                placeholderTextColor="transparent"
                keyboardType="number-pad"
                maxLength={4}
                autoFocus
              />

              <Text style={styles.entryTimerText}>
                {codeTtlSeconds > 0
                  ? `Код действует еще ${formatOtpCountdown(codeTtlSeconds)}`
                  : "Код истек. Можно запросить новый."}
              </Text>

              <Pressable
                style={styles.entryResendButton}
                onPress={onResendCode}
                disabled={!canResendCode}
              >
                <Text style={[styles.entryResendButtonText, !canResendCode && styles.entryResendButtonTextDisabled]}>
                  {authLoading && canResendCode ? "Отправляем код..." : "Отправить код заново"}
                </Text>
              </Pressable>

              {devCode ? (
                <View style={styles.entryHintCard}>
                  <Text style={styles.entryHintLabel}>Тестовый код</Text>
                  <Text style={styles.entryHintValue}>{devCode}</Text>
                </View>
              ) : null}

              {authLoading ? (
                <View style={styles.entryInlineLoader}>
                  <ActivityIndicator size="small" color="#dd362d" />
                  <Text style={styles.entryInlineLoaderText}>Проверяем код...</Text>
                </View>
              ) : null}

              {authError ? <Text style={styles.entryErrorText}>{authError}</Text> : null}
            </View>
          </View>
        )}
      </ScrollView>

      <Modal
        visible={privacyPolicyVisible}
        animationType="slide"
        transparent
        onRequestClose={() => setPrivacyPolicyVisible(false)}
      >
        <View style={styles.policyOverlay}>
          <View style={styles.policySheet}>
            <View style={styles.policyHandle} />
            <View style={styles.policyHeader}>
              <Text style={styles.policyTitle}>Политика конфиденциальности</Text>
              <Pressable
                style={styles.policyHeaderClose}
                onPress={() => setPrivacyPolicyVisible(false)}
              >
                <Text style={styles.policyHeaderCloseText}>Закрыть</Text>
              </Pressable>
            </View>

            <ScrollView style={styles.policyScroll} contentContainerStyle={styles.policyScrollContent}>
              <Text style={styles.policyUpdatedAt}>Обновлено: 11 апреля 2026</Text>
              <Text style={styles.policyParagraph}>
                Ниже краткая и честная версия политики для приложения Postamats. Мы обрабатываем только те данные,
                которые нужны для входа, аренды и работы сервиса.
              </Text>

              <Text style={styles.policySectionTitle}>1. Какие данные мы получаем</Text>
              <Text style={styles.policyBullet}>• номер телефона для входа по SMS-коду;</Text>
              <Text style={styles.policyBullet}>• данные профиля: имя, фамилия, отчество (если вы их указали);</Text>
              <Text style={styles.policyBullet}>• выбранный город, постамат, брони и аренды;</Text>
              <Text style={styles.policyBullet}>• технические данные сессии (токены, время входа, устройство/платформа);</Text>
              <Text style={styles.policyBullet}>
                • геопозиция только при вашем разрешении, чтобы считать расстояние до постаматов;
              </Text>
              <Text style={styles.policyBullet}>
                • документы и фото только если вы отправляете их для верификации или актов состояния.
              </Text>

              <Text style={styles.policySectionTitle}>2. Для чего мы используем данные</Text>
              <Text style={styles.policyBullet}>• авторизация и защита аккаунта;</Text>
              <Text style={styles.policyBullet}>• оформление брони и аренды;</Text>
              <Text style={styles.policyBullet}>• отображение доступных точек и товаров рядом;</Text>
              <Text style={styles.policyBullet}>• выполнение требований закона и предотвращение злоупотреблений.</Text>

              <Text style={styles.policySectionTitle}>3. Передача данных третьим лицам</Text>
              <Text style={styles.policyParagraph}>
                Мы не продаем персональные данные. Передача возможна только сервисам, без которых не работает продукт:
                SMS-провайдеру, платежному провайдеру (например, YooKassa) и технической инфраструктуре хранения/хостинга.
              </Text>

              <Text style={styles.policySectionTitle}>4. Хранение и безопасность</Text>
              <Text style={styles.policyParagraph}>
                Мы храним данные столько, сколько нужно для работы сервиса и выполнения обязательств. Используем
                авторизацию, разграничение доступа и журналы действий админов.
              </Text>

              <Text style={styles.policySectionTitle}>5. Ваш контроль</Text>
              <Text style={styles.policyParagraph}>
                Вы можете запросить уточнение или удаление данных через поддержку Postamats. Некоторые данные
                (например, по оплатам и арендам) могут храниться дольше, если этого требует закон.
              </Text>
            </ScrollView>

            <Pressable
              style={styles.policyConfirmButton}
              onPress={() => setPrivacyPolicyVisible(false)}
            >
              <Text style={styles.policyConfirmButtonText}>Понятно</Text>
            </Pressable>
          </View>
        </View>
      </Modal>
    </>
  );
}

export function CitySelectionScreen({
  cities,
  selectedCityId,
  onSelectCity,
  onContinue,
}: {
  cities: City[];
  selectedCityId: string;
  onSelectCity: (cityId: string) => void;
  onContinue: () => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const selectedCity = cities.find((city) => city.id === selectedCityId) ?? null;

  return (
    <ScrollView
      contentContainerStyle={styles.entryShell}
      keyboardShouldPersistTaps="handled"
      showsVerticalScrollIndicator={false}
    >
      <View style={styles.entryCenteredArea}>
        <View style={styles.entryTitleBlock}>
          <Text style={styles.entryTitle}>Выбор города</Text>
          <Text style={styles.entrySubtitle}>
            Город, в котором будут арендованы инструменты
          </Text>
        </View>

        <Pressable style={styles.softInputShell} onPress={() => setIsOpen((current) => !current)}>
          <View style={styles.softInputIconWrap}>
            <SearchGlyph />
          </View>
          <Text style={[styles.softInputText, !selectedCity && styles.softInputPlaceholder]}>
            {selectedCity?.name ?? "Город"}
          </Text>
          <ChevronGlyph open={isOpen} />
        </Pressable>

        {isOpen ? (
          <View style={styles.cityDropdownCard}>
            {cities.map((city) => {
              const active = city.id === selectedCityId;
              return (
                <Pressable
                  key={city.id}
                  style={[styles.cityDropdownItem, active && styles.cityDropdownItemActive]}
                  onPress={() => {
                    onSelectCity(city.id);
                    setIsOpen(false);
                  }}
                >
                  <Text style={[styles.cityDropdownText, active && styles.cityDropdownTextActive]}>
                    {city.name}
                  </Text>
                </Pressable>
              );
            })}
          </View>
        ) : null}

        <Pressable
          style={[styles.softPrimaryButton, !selectedCityId && styles.softPrimaryButtonDisabled]}
          onPress={onContinue}
          disabled={!selectedCityId}
        >
          <Text style={styles.softPrimaryButtonText}>Далее</Text>
        </Pressable>
      </View>
    </ScrollView>
  );
}

function PhoneGlyph() {
  return (
    <View style={styles.phoneGlyph}>
      <View style={styles.phoneGlyphScreen} />
      <View style={styles.phoneGlyphDot} />
    </View>
  );
}

function SearchGlyph() {
  return (
    <View style={styles.searchGlyph}>
      <View style={styles.searchGlyphCircle} />
      <View style={styles.searchGlyphHandle} />
    </View>
  );
}

function ChevronGlyph({ open }: { open: boolean }) {
  return (
    <View style={[styles.chevronGlyph, open && styles.chevronGlyphOpen]}>
      <View style={[styles.chevronGlyphLine, styles.chevronGlyphLineLeft]} />
      <View style={[styles.chevronGlyphLine, styles.chevronGlyphLineRight]} />
    </View>
  );
}

function AuthStepPill({
  label,
  active,
  done,
}: {
  label: string;
  active: boolean;
  done: boolean;
}) {
  return (
    <View style={[styles.authStepPill, active && styles.authStepPillActive, done && styles.authStepPillDone]}>
      <Text
        style={[
          styles.authStepPillText,
          (active || done) && styles.authStepPillTextActive,
        ]}
      >
        {done ? `✓ ${label}` : label}
      </Text>
    </View>
  );
}

function AuthTrustItem({ title, text }: { title: string; text: string }) {
  return (
    <View style={styles.authTrustItem}>
      <Text style={styles.authTrustItemTitle}>{title}</Text>
      <Text style={styles.authTrustItemText}>{text}</Text>
    </View>
  );
}

function NoDepositIllustration() {
  return (
    <View style={styles.depositArt}>
      <View style={styles.depositArtShadow} />

      <View style={styles.depositRing}>
        <View style={styles.depositRingSlash} />
      </View>

      <View style={[styles.depositBill, styles.depositBillBack]}>
        <View style={styles.depositBillCorner} />
        <View style={styles.depositBillCircle} />
      </View>

      <View style={[styles.depositBill, styles.depositBillFront]}>
        <View style={styles.depositBillCorner} />
        <View style={styles.depositBillCircle} />
      </View>

      <View style={[styles.depositCoin, styles.depositCoinTop]}>
        <View style={styles.depositCoinInner} />
      </View>
      <View style={[styles.depositCoin, styles.depositCoinRight]}>
        <View style={styles.depositCoinInner} />
      </View>
    </View>
  );
}

function WelcomeSlideIllustration({
  kind,
}: {
  kind: "no-deposit" | "nearby" | "fast" | "return";
}) {
  if (kind === "nearby") {
    return <NearbyLockerIllustration />;
  }
  if (kind === "fast") {
    return <FastBookingIllustration />;
  }
  if (kind === "return") {
    return <EasyReturnIllustration />;
  }
  return <NoDepositIllustration />;
}

function NearbyLockerIllustration() {
  return (
    <View style={styles.nearbyArt}>
      <View style={styles.nearbyArtShadow} />
      <View style={styles.nearbyPin}>
        <View style={styles.nearbyPinInner} />
      </View>
      <View style={styles.nearbyLocker}>
        <View style={styles.nearbyLockerHeader} />
        <View style={styles.nearbyLockerGrid}>
          <View style={styles.nearbyLockerCell} />
          <View style={styles.nearbyLockerCell} />
          <View style={styles.nearbyLockerCell} />
          <View style={styles.nearbyLockerCell} />
        </View>
      </View>
      <View style={styles.nearbyMapCard}>
        <View style={styles.nearbyMapRoadHorizontal} />
        <View style={styles.nearbyMapRoadVertical} />
        <View style={styles.nearbyMapDot} />
      </View>
    </View>
  );
}

function FastBookingIllustration() {
  return (
    <View style={styles.fastArt}>
      <View style={styles.fastArtShadow} />
      <View style={styles.fastPhone}>
        <View style={styles.fastPhoneTop} />
        <View style={styles.fastPhoneScreen}>
          <View style={styles.fastPhoneLineShort} />
          <View style={styles.fastPhoneLineLong} />
          <View style={styles.fastPhonePill} />
        </View>
      </View>
      <View style={styles.fastCheckBubble}>
        <View style={styles.fastCheckMarkLeft} />
        <View style={styles.fastCheckMarkRight} />
      </View>
      <View style={styles.fastSpeedLineOne} />
      <View style={styles.fastSpeedLineTwo} />
    </View>
  );
}

function EasyReturnIllustration() {
  return (
    <View style={styles.returnArt}>
      <View style={styles.returnArtShadow} />
      <View style={styles.returnCircle}>
        <View style={styles.returnArrowTop} />
        <View style={styles.returnArrowBottom} />
      </View>
      <View style={styles.returnLocker}>
        <View style={styles.returnLockerDoor} />
      </View>
      <View style={styles.returnBox}>
        <View style={styles.returnBoxTop} />
      </View>
    </View>
  );
}

